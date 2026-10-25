"""Behavior tests for real delivery and live collection; no external services."""
import contextlib
import json
import os
from pathlib import Path
from queue import Queue
import subprocess
import signal
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from tools.monitoring import integrated_alerts as m


@contextlib.contextmanager
def receiver(status=204, delay=0):
    requests = Queue()
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = self.rfile.read(int(self.headers['Content-Length']))
            requests.put((self.path, dict(self.headers), json.loads(payload)))
            if delay:
                time.sleep(delay)
            if status == 'malformed':
                self.wfile.write(b'INVALID TOPSECRET\r\n\r\n')
                self.wfile.flush()
                self.close_connection = True
                return
            self.send_response(status)
            if 300 <= status < 400:
                self.send_header('Location', '/redirect-target')
            self.end_headers()
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
    worker.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/hook', requests
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def alert():
    event = m.MetricEvent(100, 'METRIC_STREAM', 'latency_ms', 650, {'token':'do-not-send'})
    return m.Alert('latency', 'CRITICAL', event, 'latency threshold exceeded')


class WebhookTests(unittest.TestCase):
    def sink(self, url, **kwargs):
        from tools.monitoring.webhook import WebhookSink
        return WebhookSink(url, allow_http_localhost=True, **kwargs)

    def test_real_json_post_excludes_raw_metadata(self):
        with receiver() as (url, requests):
            self.sink(url).emit(alert())
            path, headers, payload = requests.get(timeout=1)
        self.assertEqual(path, '/hook')
        self.assertEqual(headers['Content-Type'], 'application/json')
        self.assertEqual(payload, {'alert':'latency','severity':'CRITICAL','category':'METRIC_STREAM',
                                  'metric':'latency_ms','value':650.0,'timestamp':100.0,
                                  'details':'latency threshold exceeded'})
        self.assertNotIn('do-not-send', json.dumps(payload))

    def test_http_requires_explicit_loopback_opt_in(self):
        from tools.monitoring.webhook import WebhookSink
        for url, flag in [('http://127.0.0.1/hook',False),('http://example.com/hook',True)]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                WebhookSink(url, allow_http_localhost=flag)

    def test_invalid_urls_and_timeout_rejected(self):
        from tools.monitoring.webhook import WebhookSink
        for url in ['file:///tmp/hook','https:///hook','https://user:pass@example.com/hook',
                    'https://example.com/hook#fragment','https://example.com:bad/hook',
                    'https://example.com/\nheader']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                WebhookSink(url)
        for timeout in [0,-1,float('nan'),float('inf'),True,61,10**10000]:
            with self.subTest(timeout_type=type(timeout).__name__), self.assertRaises(ValueError):
                WebhookSink('https://example.com/hook', timeout_sec=timeout)

    def test_non_success_is_failure_and_secrets_are_redacted(self):
        from tools.monitoring.webhook import WebhookDeliveryError
        for status in [400,429,503]:
            with self.subTest(status=status), receiver(status) as (url, requests):
                with self.assertRaises(WebhookDeliveryError) as caught:
                    self.sink(url+'?token=TOPSECRET').emit(alert())
                self.assertNotIn('TOPSECRET', str(caught.exception))
                self.assertIn(str(status), str(caught.exception))
                self.assertEqual(requests.qsize(),1)

    def test_malformed_response_is_sanitized(self):
        from tools.monitoring.webhook import WebhookDeliveryError
        with receiver('malformed') as (url, requests):
            with self.assertRaises(WebhookDeliveryError) as caught:
                self.sink(url).emit(alert())
            self.assertNotIn('TOPSECRET',str(caught.exception))

    def test_redirect_is_not_followed(self):
        from tools.monitoring.webhook import WebhookDeliveryError
        with receiver(302) as (url, requests):
            with self.assertRaises(WebhookDeliveryError):
                self.sink(url).emit(alert())
            self.assertEqual(requests.qsize(),1)

    def test_socket_timeout_is_delivery_failure(self):
        from tools.monitoring.webhook import WebhookDeliveryError
        with receiver(delay=.2) as (url, requests):
            with self.assertRaises(WebhookDeliveryError):
                self.sink(url, timeout_sec=.03).emit(alert())
            self.assertEqual(requests.qsize(),1)

    def test_failed_http_delivery_does_not_suppress_next_attempt(self):
        pipeline = m.IntegratedAlertPipeline().add_rule(
            m.AlertRule('latency','METRIC_STREAM','latency_ms',500,cooldown_sec=60))
        with receiver(503) as (url, requests):
            pipeline.add_sink(self.sink(url+'?token=TOPSECRET'))
            with self.assertLogs('tools.monitoring.integrated_alerts',level='ERROR') as logs:
                one = pipeline.ingest(alert().event)
                two = pipeline.ingest(alert().event)
            self.assertEqual((one.failed,two.failed,requests.qsize()),(1,1,2))
            self.assertNotIn('TOPSECRET','\n'.join(logs.output))




class FollowerTests(unittest.TestCase):
    def make(self, path, **kwargs):
        from tools.monitoring.tail import MetricFileFollower
        return MetricFileFollower(path, **kwargs)

    def test_existing_rows_skipped_and_appends_read_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'metrics.log'
            path.write_bytes(b'lat_ms=900\n')
            follower = self.make(path)
            self.assertEqual(follower.poll().lines, [])
            with path.open('ab') as out:
                out.write(b'lat_ms=650\n')
            self.assertEqual(follower.poll().lines, ['lat_ms=650'])
            self.assertEqual(follower.poll().lines, [])

    def test_partial_line_and_split_utf8_are_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'metrics.log'
            path.touch()
            follower = self.make(path)
            follower.poll()
            path.write_bytes(b'lat_ms=650 label=\xc3')
            self.assertEqual(follower.poll().lines, [])
            with path.open('ab') as out:
                out.write(b'\xa9\n')
            self.assertEqual(follower.poll().lines, ['lat_ms=650 label=é'])

    def test_preexisting_partial_row_is_not_parsed_as_new(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'metrics.log'
            path.write_bytes(b'ignored prefix ')
            follower = self.make(path)
            follower.poll()
            with path.open('ab') as out:
                out.write(b'lat_ms=999\nlat_ms=650\n')
            self.assertEqual(follower.poll().lines, ['lat_ms=650'])

    def test_rotation_and_truncation_reset_cursor(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'metrics.log'
            path.write_bytes(b'old metrics padding\n')
            follower = self.make(path)
            follower.poll()
            path.write_bytes(b'lat_ms=1\n')
            self.assertEqual(follower.poll().lines, ['lat_ms=1'])
            path.rename(Path(directory)/'old.log')
            path.write_bytes(b'lat_ms=2\n')
            self.assertEqual(follower.poll().lines, ['lat_ms=2'])

    def test_first_permission_failure_does_not_replay_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'metrics.log'
            path.write_bytes(b'lat_ms=999\n')
            follower=self.make(path)
            with patch('tools.monitoring.tail.os.open',side_effect=PermissionError('denied')):
                with self.assertLogs('tools.monitoring.tail',level='WARNING'):
                    self.assertEqual(follower.poll().errors,1)
            self.assertEqual(follower.poll().lines,[])
            with path.open('ab') as out:
                out.write(b'lat_ms=650\n')
            self.assertEqual(follower.poll().lines,['lat_ms=650'])

    def test_missing_file_recovers_when_created(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'metrics.log'
            follower = self.make(path)
            with self.assertLogs('tools.monitoring.tail',level='WARNING'):
                self.assertEqual(follower.poll().errors,1)
            path.write_bytes(b'lat_ms=650\n')
            self.assertEqual(follower.poll().lines, ['lat_ms=650'])

    def test_long_line_is_discarded_once_then_good_rows_continue(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'metrics.log'
            path.touch()
            follower=self.make(path,max_line_bytes=8,max_read_bytes=8)
            follower.poll()
            path.write_bytes(b'xxxxxxxxxxxxxxxxxx\nlat_ms=1\n')
            batches=[follower.poll() for _ in range(4)]
            self.assertEqual(sum(b.errors for b in batches),1)
            self.assertEqual([line for b in batches for line in b.lines],['lat_ms=1'])

    def test_invalid_utf8_is_counted_and_next_row_survives(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'metrics.log'
            path.touch()
            follower=self.make(path)
            follower.poll()
            path.write_bytes(b'lat_ms=\xff\nlat_ms=1\n')
            batch=follower.poll()
            self.assertEqual((batch.errors,batch.lines),(1,['lat_ms=1']))

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX FIFO only')
    def test_fifo_is_rejected_without_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'metrics.pipe'
            os.mkfifo(path)
            with self.assertLogs('tools.monitoring.tail',level='WARNING'):
                self.assertEqual(self.make(path).poll().errors,1)

    def test_invalid_read_limits_rejected(self):
        for limits in [{'max_line_bytes':0},{'max_read_bytes':-1},{'max_line_bytes':True}]:
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                self.make('unused',**limits)


class WatchTests(unittest.TestCase):
    def test_two_polls_read_only_new_metrics(self):
        import io
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'metrics.log'
            path.write_text('lat_ms=999\n')
            class Stop:
                def is_set(self):
                    return False
                def wait(self, interval):
                    with path.open('a') as out:
                        out.write('lat_ms=650\n')
                    return False
            engine=m.SystemAnalyzerEngine(m.IntegratedAlertPipeline())
            with contextlib.redirect_stdout(io.StringIO()) as output:
                report=m.run_watch(engine,[directory],metrics_path=path,cycles=2,
                                   interval_sec=.01,stop_event=Stop())
            self.assertEqual((report.events,report.errors),(3,0))
            self.assertIn('Cycle 2',output.getvalue())

    def test_appended_live_metric_reaches_real_receiver_once(self):
        import io
        with tempfile.TemporaryDirectory() as directory, receiver() as (url, requests):
            path=Path(directory)/'metrics.log'
            path.touch()
            class Stop:
                def is_set(self):
                    return False
                def wait(self, interval):
                    with path.open('a') as out:
                        out.write('lat_ms=650\n')
            from tools.monitoring.webhook import WebhookSink
            pipeline=m.IntegratedAlertPipeline().add_rule(
                m.AlertRule('latency','METRIC_STREAM','latency_ms',500))
            pipeline.add_sink(WebhookSink(url,allow_http_localhost=True))
            with contextlib.redirect_stdout(io.StringIO()):
                report=m.run_watch(m.SystemAnalyzerEngine(pipeline),[directory],
                                   metrics_path=path,cycles=2,interval_sec=.01,stop_event=Stop())
            self.assertEqual((report.events,report.delivered,report.errors),(3,1,0))
            self.assertEqual(requests.qsize(),1)
            self.assertEqual(requests.get(timeout=1)[2]['value'],650)

    def test_interval_and_cycles_validation(self):
        engine=m.SystemAnalyzerEngine(m.IntegratedAlertPipeline())
        for interval in [0,-1,float('nan'),True]:
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                m.run_watch(engine,[],interval_sec=interval,cycles=1)
        for cycles in [0,-1,True,1.5]:
            with self.subTest(cycles=cycles), self.assertRaises(ValueError):
                m.run_watch(engine,[],cycles=cycles)

    def test_stop_event_prevents_polling(self):
        stop=threading.Event()
        stop.set()
        report=m.run_watch(m.SystemAnalyzerEngine(m.IntegratedAlertPipeline()),[],stop_event=stop)
        self.assertEqual(report.events,0)


class LiveCliTests(unittest.TestCase):
    def run_cli(self,*args,env=None):
        return subprocess.run([sys.executable,'-m','tools.monitoring.integrated_alerts',*args],
                              cwd=Path(__file__).resolve().parents[1],capture_output=True,
                              text=True,timeout=10,env=env)

    def test_watch_two_cycles_runs_without_external_services(self):
        result=self.run_cli('--watch','--cycles','2','--interval','0.01')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('Cycle 2',result.stdout)
        self.assertIn('Collected 2 events',result.stdout)

    def test_watch_rejects_blocking_stdin_demo_and_bad_interval(self):
        for args in [('--watch','--metrics-file','-'),('--watch','--demo'),
                     ('--watch','--interval','nan'),('--watch','--cycles','0')]:
            with self.subTest(args=args):
                self.assertEqual(self.run_cli(*args).returncode,2)

    @unittest.skipUnless(os.name == 'posix', 'POSIX SIGINT delivery')
    def test_ctrl_c_stops_live_process_cleanly(self):
        process=subprocess.Popen([sys.executable,'-m','tools.monitoring.integrated_alerts',
                                  '--watch','--interval','0.1'],
                                 cwd=Path(__file__).resolve().parents[1],
                                 stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        ready=threading.Event()
        def read_first_cycle():
            if 'Cycle 1' in process.stdout.readline():
                ready.set()
        reader=threading.Thread(target=read_first_cycle,daemon=True)
        reader.start()
        try:
            self.assertTrue(ready.wait(3),'live process did not report first cycle')
            reader.join(timeout=1)
            process.send_signal(signal.SIGINT)
            stdout,stderr=process.communicate(timeout=5)
            self.assertEqual(process.returncode,130,stderr)
            self.assertIn('Monitoring stopped',stdout)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=3)

    def test_webhook_missing_env_fails_before_collection(self):
        env=dict(os.environ)
        env.pop('MONITOR_WEBHOOK_URL',None)
        result=self.run_cli('--webhook',env=env)
        self.assertEqual(result.returncode,2)
        self.assertNotIn('Collected',result.stdout)

    def test_cli_delivers_demo_to_explicit_local_receiver(self):
        with receiver() as (url,requests):
            env=dict(os.environ,MONITOR_WEBHOOK_URL=url)
            result=self.run_cli('--webhook','--allow-http-localhost','--demo',env=env)
            self.assertEqual(result.returncode,0,result.stderr)
            payloads=[requests.get(timeout=1)[2] for _ in range(requests.qsize())]
            self.assertTrue({'latency_ms','memory_mb'} <= {p['metric'] for p in payloads})


if __name__ == '__main__':
    unittest.main()
