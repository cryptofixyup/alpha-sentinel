import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.monitoring import integrated_alerts as m


class Clock:
    def __init__(self): self.now=0.0
    def __call__(self): return self.now


class ParserTests(unittest.TestCase):
    def parser(self, **kw):
        from tools.monitoring.security_events import LogDigester
        return LogDigester(**kw)

    def test_formats_keep_units_distinct_and_strip_queries(self):
        p=self.parser()
        web=p.parse('192.0.2.1 - alice [24/Oct/2026:10:00:00 +0000] "POST /login?token=SECRET HTTP/1.1" 401 128',100)
        api=p.parse('{"ip":"192.0.2.1","lat_ms":30,"path":"/login"}',100)
        self.assertEqual([(v.name,v.unit,v.value) for v in web.metrics],[('response_bytes','bytes',128)])
        self.assertEqual([(v.name,v.unit,v.value) for v in api.metrics],[('latency_ms','ms',30)])
        self.assertEqual(web.target_resource,'/login')
        self.assertEqual(web.action,'WEB_ACCESS')
        self.assertIsNotNone(web.source_timestamp)

    def test_missing_identity_and_measurements_stay_absent(self):
        event=self.parser().parse('{"action":"API_REQUEST"}',100)
        self.assertIsNone(event.source_ip)
        self.assertIsNone(event.user_id)
        self.assertEqual(event.metrics,())
        self.assertIsNone(self.parser().parse('ip=0.0.0.0 lat_ms=0',100).source_ip)

    def test_quoted_kv_fields_are_unquoted(self):
        event=self.parser().parse('ip=192.0.2.1 user="alice smith" action=LOGIN_FAILED path=/login lat_ms=0 status=401',100)
        self.assertEqual(event.user_id,'alice smith')
        self.assertEqual(event.metrics[0].value,0)

    def test_time_of_day_does_not_guess_a_date(self):
        e=self.parser().parse('time=10:00:01 lat_ms=30',100)
        self.assertIsNone(e.source_timestamp)
        self.assertEqual(e.source_time_text,'10:00:01')

    def test_syslog_pid_authentication_failure(self):
        e=self.parser().parse('Oct 24 10:00:00 host sshd[123]: Failed password for invalid user bob from 192.0.2.2 port 22 ssh2',100)
        self.assertEqual((e.source_ip,e.user_id,e.action),('192.0.2.2','bob','LOGIN_FAILED'))
        self.assertIsNone(e.source_timestamp)

    def test_malformed_rows_rejected_without_type_errors(self):
        from tools.monitoring.security_events import ParseError
        rows=['{"status":null}','{"status":true}','{"status":200.5}',
              '{"lat_ms":true}','{"lat_ms":NaN}','{"lat_ms":1e309}',
              '{"ip":[]}','{"user":{}}','{"time":null}',
              'ip=not-an-ip lat_ms=1','status=oops lat_ms=1','lat_ms=',
              'lat_ms="bad"','lat_ms=-1','lat_ms=1000000000001',
              'lat_ms=1 lat_ms=2','user="unterminated','{"action":"FAIL"',
              'garbage unrelated row']
        for row in rows:
            with self.subTest(row=row),self.assertRaises(ParseError): self.parser().parse(row,100)

    def test_input_size_and_timestamp_validation(self):
        from tools.monitoring.security_events import ParseError
        with self.assertRaises(ParseError): self.parser(max_line_bytes=32).parse('x'*33,100)
        with self.assertRaises(ParseError): self.parser().parse('lat_ms=1',float('nan'))
        e=self.parser().parse('{"time":"2026-10-24T10:00:00+00:00","lat_ms":1}',100)
        self.assertIsNotNone(e.source_timestamp)
        self.assertEqual(e.received_at,100)


class DetectorTests(unittest.TestCase):
    def engine(self,clock=None,**kw):
        from tools.monitoring.security_detector import UnifiedSecurityEngine
        return UnifiedSecurityEngine(clock=clock or Clock(),**kw)

    def row(self,ip='192.0.2.1',user='alice',action='LOGIN_FAILED',**kw):
        return json.dumps(dict(ip=ip,user=user,action=action,path='/login',**kw))

    def test_flat_baseline_detects_first_large_spike(self):
        engine=self.engine()
        for _ in range(5): engine.ingest_raw_log(self.row(action='API_REQUEST',lat_ms=30),100)
        result=engine.ingest_raw_log(self.row(action='API_REQUEST',lat_ms=350),100)
        self.assertEqual([a.alert_type for a in result.observations],['SUSPECTED_METRIC_OUTLIER'])
        a=result.observations[0]
        self.assertEqual((a.metric_name,a.metric_unit,a.anomaly.mean),('latency_ms','ms',30))
        self.assertGreater(a.anomaly.z_score,3)
        self.assertEqual(a.anomaly.prior_samples,5)

    def test_bytes_and_resources_do_not_pollute_latency_baseline(self):
        engine=self.engine()
        for _ in range(5): engine.ingest_raw_log(self.row(action='API_REQUEST',lat_ms=30),100)
        web='192.0.2.1 - alice [24/Oct/2026:10:00:00 +0000] "POST /login HTTP/1.1" 401 128'
        self.assertEqual(engine.ingest_raw_log(web,100).observations,())
        other=json.dumps({'ip':'192.0.2.1','path':'/other','lat_ms':900})
        self.assertEqual(engine.ingest_raw_log(other,100).observations,())
        result=engine.ingest_raw_log(self.row(action='API_REQUEST',lat_ms=30),100)
        self.assertEqual(result.observations,())

    def test_outlier_does_not_train_baseline(self):
        engine=self.engine()
        for _ in range(5): engine.ingest_raw_log(self.row(action='API_REQUEST',lat_ms=30),100)
        engine.ingest_raw_log(self.row(action='API_REQUEST',lat_ms=350),100)
        again=engine.ingest_raw_log(self.row(action='API_REQUEST',lat_ms=350),100)
        self.assertEqual(again.observations[0].anomaly.mean,30)
        self.assertEqual(engine.ingest_raw_log(self.row(action='API_REQUEST',lat_ms=30),100).observations,())

    def test_only_explicit_auth_failures_count(self):
        engine=self.engine()
        for _ in range(8):
            r=engine.ingest_raw_log(self.row(action='DOWNLOAD_FAILED',status=403),100)
            self.assertEqual(r.observations,())
        for i,user in enumerate(['alice','bob','charlie','david']):
            r=engine.ingest_raw_log(self.row(user=user),100)
        self.assertEqual(r.observations[0].alert_type,'SUSPECTED_PASSWORD_SPRAY')
        self.assertEqual(r.observations[0].evidence_count,4)
        self.assertEqual(len(r.observations[0].evidence_ids),4)

    def test_unknown_sources_never_pool(self):
        engine=self.engine()
        for user in ['a','b','c','d','e','f']:
            r=engine.ingest_raw_log(json.dumps({'user':user,'action':'LOGIN_FAILED','lat_ms':900}),100)
            self.assertIsNone(r.event.source_ip)
            self.assertEqual(r.observations,())
        self.assertEqual(engine.state_sizes()['sources'],0)
        self.assertEqual(engine.state_sizes()['series'],0)

    def test_receipt_window_ignores_source_clock_skew_and_order(self):
        clock=Clock(); engine=self.engine(clock=clock,window_seconds=10)
        for source_time in [9999999999,1,9999999998]:
            engine.ingest_raw_log(self.row(time=source_time),100)
        clock.now=11
        r=engine.ingest_raw_log(self.row(time=0),100)
        self.assertEqual(r.observations,())
        self.assertEqual(engine.state_sizes()['failures'],1)

    def test_window_boundary_expires_old_failures(self):
        clock=Clock(); engine=self.engine(clock=clock,window_seconds=10)
        for _ in range(3): engine.ingest_raw_log(self.row(),100)
        clock.now=10
        self.assertEqual(engine.ingest_raw_log(self.row(),100).observations,())

    def test_caps_expiry_and_eviction_are_visible(self):
        clock=Clock(); engine=self.engine(clock=clock,max_sources=2,max_series=2,max_failures_per_source=4,state_ttl_sec=10)
        for i in range(8):
            engine.ingest_raw_log(self.row(ip=f'192.0.2.{i+1}',lat_ms=30),100)
        sizes=engine.state_sizes()
        self.assertLessEqual(sizes['sources'],2); self.assertLessEqual(sizes['series'],2)
        self.assertGreater(sizes['evictions'],0)
        for _ in range(8): r=engine.ingest_raw_log(self.row(),100)
        self.assertLessEqual(engine.state_sizes()['failures'],8)
        self.assertTrue(r.observations[0].evidence_truncated)
        clock.now=11
        engine.ingest_raw_log('{}',100)
        self.assertEqual(engine.state_sizes()['sources'],0)
        self.assertEqual(engine.state_sizes()['series'],0)

    def test_alert_evidence_is_immutable(self):
        engine=self.engine()
        for user in ['a','b','c','d']: r=engine.ingest_raw_log(self.row(user=user),100)
        old=r.observations[0]; ids=old.evidence_ids; targets=old.targets
        engine.ingest_raw_log(self.row(user='new'),100)
        self.assertEqual(old.evidence_ids,ids); self.assertEqual(old.targets,targets)
        self.assertIsInstance(old.targets,frozenset)

    def test_configuration_is_validated(self):
        for config in [{'window_seconds':0},{'max_sources':True},{'max_series':0},
                       {'max_failures_per_source':3},{'state_ttl_sec':float('inf')}]:
            with self.subTest(config=config),self.assertRaises(ValueError): self.engine(**config)





class CaptureSink:
    def __init__(self, fail=False): self.alerts=[]; self.fail=fail
    def emit(self, alert):
        if self.fail: raise OSError('delivery failed')
        self.alerts.append(alert)


class BridgeTests(unittest.TestCase):
    def test_suspected_pattern_reaches_existing_sinks_with_evidence(self):
        from tools.monitoring.security_detector import UnifiedSecurityEngine
        sink=CaptureSink()
        pipeline=m.IntegratedAlertPipeline().add_sink(sink)
        engine=m.SystemAnalyzerEngine(pipeline,security_engine=UnifiedSecurityEngine(clock=Clock()))
        rows=[json.dumps({'ip':'192.0.2.1','user':u,'action':'LOGIN_FAILED','path':'/login?token=SECRET'})
              for u in ['alice','bob','charlie','david','edward']]
        report=engine.parse_and_analyze_stream(rows)
        self.assertEqual((report.events,report.errors,report.delivered),(5,0,1))
        a=sink.alerts[0]
        self.assertEqual(a.event.category,'SECURITY')
        self.assertEqual(a.evidence['evidence_count'],4)
        self.assertEqual(len(a.evidence['content_hashes']),4)
        self.assertNotIn('SECRET',json.dumps(a.evidence))
        self.assertNotIn('alice',json.dumps(a.evidence))
        self.assertIn('Suspected',a.details)

    def test_delivery_failure_does_not_burn_observation_cooldown(self):
        clock=Clock(); pipeline=m.IntegratedAlertPipeline(clock=clock)
        failed,good=CaptureSink(True),CaptureSink()
        pipeline.add_sink(failed).add_sink(good)
        a=m.Alert('suspected','MEDIUM',m.MetricEvent(100,'SECURITY','failures',4,{}),'Suspected auth pattern')
        with self.assertLogs('tools.monitoring.integrated_alerts',level='ERROR'):
            one=pipeline.dispatch_observation(a,('auth','192.0.2.1'),30)
        failed.fail=False
        two=pipeline.dispatch_observation(a,('auth','192.0.2.1'),30)
        self.assertEqual((one.delivered,one.failed,two.delivered,two.suppressed),(1,1,1,1))
        self.assertEqual((len(failed.alerts),len(good.alerts)),(1,1))

    def test_observation_cooldown_state_is_capped_and_expires(self):
        clock=Clock(); pipeline=m.IntegratedAlertPipeline(clock=clock,observation_capacity=2)
        pipeline.add_sink(CaptureSink())
        a=m.Alert('suspected','MEDIUM',m.MetricEvent(100,'SECURITY','failures',4,{}),'Suspected auth pattern')
        for key in ['a','b','c']: pipeline.dispatch_observation(a,key,30)
        self.assertEqual(pipeline.observation_state_size(),2)
        clock.now=31
        pipeline.dispatch_observation(a,'d',30)
        self.assertEqual(pipeline.observation_state_size(),1)

    def test_malformed_security_rows_are_counted(self):
        from tools.monitoring.security_detector import UnifiedSecurityEngine
        engine=m.SystemAnalyzerEngine(m.IntegratedAlertPipeline(),security_engine=UnifiedSecurityEngine())
        with self.assertLogs('tools.monitoring.integrated_alerts',level='WARNING'):
            r=engine.parse_and_analyze_stream(['status=bad','{"lat_ms":null}',''])
        self.assertEqual((r.events,r.errors),(0,2))

    def test_webhook_keeps_structured_security_evidence(self):
        from tools.monitoring.webhook import WebhookSink
        from test_monitoring_live import receiver
        evidence={'classification':'suspected','evidence_count':4,'content_hashes':['a'*64]}
        a=m.Alert('suspected','MEDIUM',m.MetricEvent(100,'SECURITY','failures',4,{}),
                  'Suspected auth pattern',evidence=evidence)
        with receiver() as (url,requests):
            WebhookSink(url,allow_http_localhost=True).emit(a)
            payload=requests.get(timeout=1)[2]
        self.assertEqual(payload['evidence'],evidence)

    def test_security_cli_runs_supported_log_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'auth.log'
            path.write_text('\n'.join(json.dumps({'ip':'192.0.2.1','user':u,'action':'LOGIN_FAILED'})
                                      for u in ['a','b','c','d']))
            r=subprocess.run([sys.executable,'-m','tools.monitoring.integrated_alerts',
                              '--security','--metrics-file',str(path)],
                             cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=10)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn('SUSPECTED_PASSWORD_SPRAY',r.stdout)
        self.assertIn('content_hashes',r.stdout)


if __name__=='__main__': unittest.main()
