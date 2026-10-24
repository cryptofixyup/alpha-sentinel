import unittest
import tempfile
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
from collections import namedtuple
from tools.monitoring import integrated_alerts as m

class Clock:
    now = 0.0
    def __call__(self):
        return self.now

class Sink:
    def __init__(self, fail=False):
        self.fail, self.alerts = fail, []
    def emit(self, alert):
        if self.fail:
            raise OSError('delivery unavailable')
        self.alerts.append(alert)

def event(value=11):
    return m.MetricEvent(100, 'METRIC_STREAM', 'latency_ms', value, {})

def rule(**kw):
    return m.AlertRule('latency', 'METRIC_STREAM', 'latency_ms', **({'threshold': 10} | kw))

class RuleTests(unittest.TestCase):
    def test_operators_and_boundaries(self):
        for op, value, want in [('>',10,False),('>',11,True),('>=',10,True),('>=',9,False),('<',9,True),('<',10,False),('<=',10,True),('<=',11,False),('==',10,True),('==',11,False)]:
            with self.subTest(op=op,value=value):
                self.assertEqual(rule(condition=op).evaluate(event(value)) is not None, want)
    def test_invalid_operator_rejected(self):
        for op in ['!=', '', '=>']:
            with self.subTest(op=op), self.assertRaises(ValueError):
                rule(condition=op)
    def test_bad_thresholds_rejected(self):
        for value in [float('nan'), float('inf'), -float('inf'), True, '10']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                rule(threshold=value)
    def test_bad_cooldowns_rejected(self):
        for value in [-1, float('inf'), float('nan'), True]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                rule(cooldown_sec=value)
    def test_invalid_event_values_rejected(self):
        for value in [float('nan'), float('inf'), -float('inf'), True, '11']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                event(value)
    def test_invalid_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            m.MetricEvent(float('nan'),'x','x',1,{})
    def test_unrelated_metric_ignored(self):
        self.assertIsNone(rule().evaluate(m.MetricEvent(1,'DISK','other',20,{})))

class PipelineTests(unittest.TestCase):
    def setup_pipeline(self):
        clock = Clock()
        p = m.IntegratedAlertPipeline(clock=clock)
        p.add_rule(rule(cooldown_sec=3))
        return p, clock
    def test_failure_does_not_block_later_sink(self):
        p, _ = self.setup_pipeline()
        bad, good = Sink(True), Sink()
        p.add_sink(bad).add_sink(good)
        with self.assertLogs('tools.monitoring.integrated_alerts', level='ERROR'):
            report = p.ingest(event())
        self.assertEqual(len(good.alerts),1)
        self.assertEqual((report.delivered,report.failed),(1,1))
    def test_failed_sink_retries_while_successful_sink_is_suppressed(self):
        p, clock = self.setup_pipeline()
        bad, good = Sink(True), Sink()
        p.add_sink(bad).add_sink(good)
        with self.assertLogs('tools.monitoring.integrated_alerts', level='ERROR'):
            p.ingest(event())
        bad.fail = False
        clock.now = 1
        report = p.ingest(event())
        self.assertEqual((len(bad.alerts),len(good.alerts)),(1,1))
        self.assertEqual((report.delivered,report.suppressed),(1,1))
    def test_initial_zero_clock_and_exact_boundary(self):
        p, clock = self.setup_pipeline()
        sink = Sink()
        p.add_sink(sink)
        p.ingest(event())
        clock.now = 2.999
        p.ingest(event())
        clock.now = 3
        p.ingest(event())
        self.assertEqual(len(sink.alerts),2)
    def test_no_sink_does_not_consume_cooldown(self):
        p, _ = self.setup_pipeline()
        p.ingest(event())
        sink = Sink()
        p.add_sink(sink)
        p.ingest(event())
        self.assertEqual(len(sink.alerts),1)

class AnalyzerTests(unittest.TestCase):
    def test_malformed_nonfinite_and_negative_stream_values_are_counted(self):
        p = m.IntegratedAlertPipeline().add_rule(rule(cooldown_sec=0))
        sink = Sink()
        p.add_sink(sink)
        engine = m.SystemAnalyzerEngine(p)
        with self.assertLogs('tools.monitoring.integrated_alerts', level='WARNING'):
            report = engine.parse_and_analyze_stream(['lat_ms=nan mem_mb=-1','lat_ms=oops','lat_ms=inf','lat_ms=11 mem_mb=0'])
        self.assertEqual(report.errors,4)
        self.assertEqual(report.events,2)
        self.assertEqual(len(sink.alerts),1)
    def test_empty_recognized_metrics_are_errors(self):
        engine = m.SystemAnalyzerEngine(m.IntegratedAlertPipeline())
        with self.assertLogs('tools.monitoring.integrated_alerts', level='WARNING'):
            report = engine.parse_and_analyze_stream(['lat_ms= mem_mb='])
        self.assertEqual((report.events, report.errors), (0, 2))

    def test_partial_read_failure_preserves_counts(self):
        for exception in [OSError('read failed'), UnicodeError('invalid encoding')]:
            with self.subTest(exception=exception):
                def lines():
                    yield 'lat_ms=11 mem_mb=bad'
                    raise exception
                pipeline = m.IntegratedAlertPipeline().add_rule(rule(cooldown_sec=0))
                good, bad = Sink(), Sink(True)
                pipeline.add_sink(bad).add_sink(good)
                with self.assertLogs('tools.monitoring.integrated_alerts', level='WARNING'):
                    report = m.SystemAnalyzerEngine(pipeline).parse_and_analyze_stream(lines())
                self.assertEqual((report.events, report.errors), (1, 2))
                self.assertEqual((report.delivered, report.delivery_failures), (1, 1))
                self.assertEqual(len(good.alerts), 1)

    def test_disk_failure_does_not_block_other_paths(self):
        p = m.IntegratedAlertPipeline()
        engine = m.SystemAnalyzerEngine(p)
        Usage = namedtuple('usage','total used free')
        with patch('tools.monitoring.integrated_alerts.shutil.disk_usage', side_effect=[PermissionError('denied'),Usage(100,85,15)]):
            with self.assertLogs('tools.monitoring.integrated_alerts',level='WARNING'):
                report = engine.analyze_disk_usage(['/bad','/good path'])
        self.assertEqual((report.events,report.errors),(1,1))
    def test_real_disk_collection(self):
        engine = m.SystemAnalyzerEngine(m.IntegratedAlertPipeline())
        with tempfile.TemporaryDirectory() as directory:
            report = engine.analyze_disk_usage([directory])
        self.assertEqual((report.events,report.errors),(1,0))
    def test_invalid_disk_totals_rejected(self):
        engine = m.SystemAnalyzerEngine(m.IntegratedAlertPipeline())
        Usage = namedtuple('usage','total used free')
        with patch('tools.monitoring.integrated_alerts.shutil.disk_usage',return_value=Usage(0,0,0)):
            with self.assertLogs('tools.monitoring.integrated_alerts',level='WARNING'):
                report = engine.analyze_disk_usage(['/'])
        self.assertEqual((report.events,report.errors),(0,1))



class CliTests(unittest.TestCase):
    def run_cli(self, *args, input=None):
        return subprocess.run(
            [sys.executable, '-m', 'tools.monitoring.integrated_alerts', *args],
            cwd=Path(__file__).resolve().parents[1], input=input,
            capture_output=True, text=True, timeout=10)

    def test_default_has_no_synthetic_stream_alerts(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_cli('--disk-path', directory)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Collected 1 events', result.stdout)
        self.assertNotIn('API High Latency', result.stdout)

    def test_explicit_demo_preserves_sample_alerts(self):
        result = self.run_cli('--demo')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('API High Latency', result.stdout)
        self.assertIn('High Memory', result.stdout)

    def test_metrics_file_and_path_with_spaces(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'metrics sample.log'
            source.write_text('lat_ms=650 mem_mb=350\n', encoding='utf-8')
            result = self.run_cli('--disk-path', directory, '--metrics-file', str(source))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Collected 3 events', result.stdout)
        self.assertIn('API High Latency', result.stdout)

    def test_stdin_metrics(self):
        result = self.run_cli('--metrics-file', '-', input='lat_ms=650\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('API High Latency', result.stdout)

    def test_bad_metrics_return_nonzero(self):
        result = self.run_cli('--metrics-file', '-', input='lat_ms=nan\n')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Invalid metric', result.stderr)

    def test_missing_metrics_file_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_cli('--metrics-file', str(Path(directory) / 'missing.log'))
        self.assertEqual(result.returncode, 1)
        self.assertIn('Metric input failed', result.stderr)

    def test_missing_disk_path_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_cli('--disk-path', str(Path(directory) / 'missing'))
        self.assertEqual(result.returncode, 1)
        self.assertIn('Disk collection failed', result.stderr)


if __name__ == '__main__':
    unittest.main()
