"""Regression tests for v4.2 helpers. Temporary projects only; no network or paid API."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/f'{name}.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
prepare=load('prepare_example')
code_map=load('code_map')
probe=load('probe_l00')

class Base(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.project=self.base/'project';shutil.copytree(ROOT/'starter',self.project)
    def tearDown(self): self.temp.cleanup()
    def cli(self,tool,*args):
        return subprocess.run([sys.executable,'-B',str(ROOT/'tools'/tool),*map(str,args)],capture_output=True,text=True,timeout=20)

class TestPrepare(Base):
    def test_all_34_examples_are_exact_copies(self):
        m=json.loads((ROOT/'course-manifest.json').read_text())
        for lesson in m['order']:
            with self.subTest(lesson=lesson):
                out=prepare.prepare(lesson,self.project)
                source=ROOT/out['source'];copy=self.project/out['copy']
                self.assertEqual(source.read_bytes(),copy.read_bytes())
                self.assertEqual(hashlib.sha256(copy.read_bytes()).hexdigest(),out['source_sha256'])
                self.assertEqual(out['course_version'],'4.2.0')
    def test_no_overwrite_preserves_student_edits(self):
        out=prepare.prepare('L00',self.project);p=self.project/out['copy'];p.write_text('# my work')
        with self.assertRaises(ValueError):prepare.prepare('L00',self.project)
        self.assertEqual(p.read_text(),'# my work')
    def test_invalid_lesson(self):
        with self.assertRaises(ValueError):prepare.prepare('X99',self.project)
    def test_missing_project(self):
        with self.assertRaises(ValueError):prepare.prepare('L00',self.base/'missing')
    def test_course_is_not_application(self):
        with self.assertRaises(ValueError):prepare.prepare('L00',ROOT)
    def test_symlink_destination_is_refused(self):
        outside=self.base/'outside';outside.mkdir();(self.project/'.local').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(ValueError):prepare.prepare('L00',self.project)
        self.assertEqual(list(outside.iterdir()),[])
    def test_cli_invalid_lesson_is_structured_error(self):
        r=self.cli('prepare_example.py','X99','--project',self.project)
        self.assertEqual(r.returncode,2);self.assertEqual(json.loads(r.stdout)['status'],'blocked')

class TestProbe(Base):
    def setUp(self):super().setUp();prepare.prepare('L00',self.project)
    def test_integer_42_is_actual_attribute_error_no_client(self):
        r=probe.probe(self.project,42)
        self.assertEqual(r['exception_type'],'AttributeError');self.assertIsNone(r['result']);self.assertEqual(r['client_calls'],0)
    def test_text_42_succeeds_with_one_call(self):
        r=probe.probe(self.project,'42')
        self.assertEqual(r['result'],'succeeded');self.assertIsNone(r['exception_type']);self.assertEqual(r['client_arguments'],['42'])
    def test_blank_rejected_without_client(self):
        r=probe.probe(self.project,'   ');self.assertEqual(r['result'],'invalid_input');self.assertEqual(r['client_calls'],0)
    def test_empty_response_is_invalid(self):
        r=probe.probe(self.project,'task','');self.assertEqual(r['result'],'invalid_response');self.assertEqual(r['client_calls'],1)
    def test_none_response_records_exception_after_call(self):
        r=probe.probe(self.project,'task',None);self.assertEqual(r['exception_type'],'AttributeError');self.assertEqual(r['client_calls'],1)
    def test_cli_text_has_no_json_quoting_requirement(self):
        r=self.cli('probe_l00.py','--project',self.project,'--task-text','42')
        self.assertEqual(r.returncode,0);self.assertEqual(json.loads(r.stdout)['task_type'],'str')
    def test_cannot_probe_missing_copy(self):
        shutil.rmtree(self.project/'.local')
        with self.assertRaises(ValueError):probe.probe(self.project,42)
    def test_syntax_error_is_not_reported_as_success(self):
        (self.project/'.local/concepts/L00/00-example.py').write_text('def broken(:')
        r=self.cli('probe_l00.py','--project',self.project,'--task-json','42')
        self.assertEqual(r.returncode,2);self.assertEqual(json.loads(r.stdout)['status'],'blocked')

class TestCodeMap(Base):
    def setUp(self):
        super().setUp()
        self.file=self.project/'devagent/mapped.py'
        self.file.write_text('raise RuntimeError("MUST NOT EXECUTE")\n\ndef entry(task):\n    return task\n',encoding='utf-8')
        self.map_path=self.project/'docs/learning-records/L00-code-map.json';self.map_path.parent.mkdir(parents=True,exist_ok=True)
        self.mapping={'lesson':'L00','source_head':None,'entries':[
            {'role':role,'status':'observed','path':'devagent/mapped.py','symbol':'entry','anchor':'def entry(task):','sha256':hashlib.sha256(self.file.read_bytes()).hexdigest()}
            for role in sorted(code_map.ROLES)]}
        self.write_map()
    def write_map(self): self.map_path.write_text(json.dumps(self.mapping,ensure_ascii=False),encoding='utf-8')
    def check(self):self.write_map();return code_map.validate(self.project,self.map_path)
    def test_real_references_valid_without_running_code(self):
        r=self.check();self.assertEqual(r['status'],'references_valid');self.assertEqual(len(r['checked']),5)
    def test_inventory_ast_only_no_execution(self):
        r=code_map.inventory(self.project);f=next(x for x in r['files'] if x['path']=='devagent/mapped.py')
        self.assertEqual(f['symbols'][0]['name'],'entry');self.assertEqual(f['symbols'][0]['line'],3)
    def test_modified_file_invalidates_map(self):
        self.file.write_text(self.file.read_text()+'# changed\n');self.assertEqual(self.check()['status'],'invalid')
    def test_invented_symbol_rejected(self):
        self.mapping['entries'][0]['symbol']='imaginary_handler';self.assertEqual(self.check()['status'],'invalid')
    def test_invented_anchor_rejected(self):
        self.mapping['entries'][0]['anchor']='return some_imaginary_value';self.assertEqual(self.check()['status'],'invalid')
    def test_missing_roles_not_complete(self):
        self.mapping['entries']=self.mapping['entries'][:1];self.assertEqual(self.check()['status'],'incomplete')
    def test_planned_is_not_observed(self):
        self.mapping['entries'][0]['status']='planned';self.assertEqual(self.check()['status'],'incomplete')
    def test_parent_escape_rejected(self):
        self.mapping['entries'][0]['path']='../outside.py';self.assertEqual(self.check()['status'],'invalid')
    def test_symlink_file_rejected(self):
        target=self.project/'devagent/link.py';target.symlink_to(self.file)
        self.mapping['entries'][0]['path']='devagent/link.py';self.assertEqual(self.check()['status'],'invalid')
    def test_symlink_map_rejected(self):
        link=self.project/'docs/map-link.json';link.symlink_to(self.map_path)
        with self.assertRaises(ValueError):code_map.validate(self.project,link)
    def test_malformed_top_level(self):
        self.map_path.write_text('[]')
        with self.assertRaises(ValueError):code_map.validate(self.project,self.map_path)
    def test_cli_does_not_write_map(self):
        before=self.map_path.read_bytes();r=self.cli('code_map.py','validate','--project',self.project,'--map',self.map_path)
        self.assertEqual(r.returncode,0);self.assertEqual(self.map_path.read_bytes(),before)
    def test_pack_includes_current_map_not_other_answers(self):
        out=self.base/'handoff.zip';r=self.cli('course.py','pack','L00','--project',self.project,'--output',out)
        self.assertEqual(r.returncode,0,r.stdout)
        with zipfile.ZipFile(out) as z:
            self.assertIn('docs/learning-records/L00-code-map.json',z.namelist())
            self.assertIn('L00-02-交给AI.md',z.namelist())
            self.assertFalse(any('04-复习' in n or 'answers/' in n for n in z.namelist()))

if __name__=='__main__':unittest.main(verbosity=2)
