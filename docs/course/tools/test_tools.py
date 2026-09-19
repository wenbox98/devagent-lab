"""学习工具自身回归：测试在临时目录，不覆盖学习者项目、不联网。"""
import json,shutil,subprocess,sys,tempfile,unittest,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class TestCourseTools(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def run_cli(self,*args):
        return subprocess.run([sys.executable,'-B',str(ROOT/'tools/course.py'),*map(str,args)],capture_output=True,text=True,timeout=20)
    def project(self):
        d=self.p/'project';shutil.copytree(ROOT/'starter',d);return d
    def test_doctor_no_api(self):
        r=self.run_cli('doctor');self.assertEqual(r.returncode,0,r.stderr);self.assertFalse(json.loads(r.stdout)['paid_api_called'])
    def test_init_new_project(self):
        d=self.p/'new';r=self.run_cli('init',d);self.assertEqual(r.returncode,0,r.stderr)
        self.assertTrue((d/'docs/course/lessons/L00/02-交给AI.md').exists())
        self.assertTrue((d/'fixtures/tiny_repo/pagination.py').exists())
        self.assertIn('NotImplementedError',(d/'devagent/app.py').read_text())
    def test_init_existing_refused(self):
        d=self.p/'existing';d.mkdir();(d/'keep.txt').write_text('keep')
        self.assertEqual(self.run_cli('init',d).returncode,2);self.assertEqual((d/'keep.txt').read_text(),'keep')
    def test_init_inside_course_refused(self):
        d=ROOT/'refuse-this-test-project';self.assertFalse(d.exists())
        self.assertEqual(self.run_cli('init',d).returncode,2);self.assertFalse(d.exists())
    def test_pack_one_instruction_and_hashes(self):
        d=self.project();out=self.p/'pack.zip';r=self.run_cli('pack','L00','--project',d,'--output',out);self.assertEqual(r.returncode,0,r.stdout)
        with zipfile.ZipFile(out) as z:
            names=z.namelist();self.assertIn('L00-02-交给AI.md',names);self.assertIn('devagent/app.py',names)
            self.assertFalse(any('04-' in n or 'docs/course' in n for n in names))
            self.assertEqual(z.read('L00-02-交给AI.md'),(ROOT/'lessons/L00/02-交给AI.md').read_bytes())
            self.assertTrue(json.loads(z.read('source-manifest.json'))['files'])
    def test_pack_does_not_include_environment(self):
        d=self.project();(d/'.env').write_text('MY_KEY=confidential');(d/'devagent/.env').write_text('confidential');out=self.p/'pack.zip'
        self.assertEqual(self.run_cli('pack','L01','--project',d,'--output',out).returncode,0)
        with zipfile.ZipFile(out) as z:self.assertFalse(any('.env' in n for n in z.namelist()))
    def test_pack_detects_obvious_key(self):
        d=self.project();(d/'devagent/config.py').write_text('key="sk-'+('a'*32)+'"');out=self.p/'pack.zip'
        self.assertEqual(self.run_cli('pack','L00','--project',d,'--output',out).returncode,2);self.assertFalse(out.exists())
    def test_pack_excludes_symlink(self):
        d=self.project();outside=self.p/'private.py';outside.write_text('private=True')
        try:(d/'devagent/leak.py').symlink_to(outside)
        except OSError:self.skipTest('symlinks not supported')
        out=self.p/'pack.zip';self.assertEqual(self.run_cli('pack','L00','--project',d,'--output',out).returncode,0)
        with zipfile.ZipFile(out) as z:self.assertNotIn('devagent/leak.py',z.namelist())
    def test_pack_never_overwrites(self):
        d=self.project();out=self.p/'pack.zip';out.write_bytes(b'preserve')
        self.assertEqual(self.run_cli('pack','L00','--project',d,'--output',out).returncode,2);self.assertEqual(out.read_bytes(),b'preserve')
    def test_unknown_lesson_refused(self):
        d=self.project();self.assertEqual(self.run_cli('pack','X99','--project',d,'--output',self.p/'x.zip').returncode,2)
    def test_lab_copy_no_answer(self):
        d=self.project();r=self.run_cli('lab','--project',d);self.assertEqual(r.returncode,0,r.stdout)
        self.assertTrue((d/'.local/workshops/bug_lab/student.py').exists());self.assertFalse((d/'.local/workshops/answers').exists())
        self.assertEqual(self.run_cli('lab','--project',d).returncode,2)
    def test_review_dates(self):
        p=self.p/'progress.json';p.write_text(json.dumps({'completed':{'L00':'2026-09-18'}}))
        r=self.run_cli('review',p,'--today','2026-09-21');self.assertEqual(r.returncode,0,r.stdout)
        dates=json.loads(r.stdout)['review_dates'];self.assertEqual([x['date'] for x in dates],['2026-09-19','2026-09-21','2026-09-25','2026-10-09'])
        self.assertEqual([x['due'] for x in dates],[True,True,False,False])
    def test_review_invalid_date(self):
        p=self.p/'progress.json';p.write_text(json.dumps({'completed':{'L00':'no-date'}}));self.assertEqual(self.run_cli('review',p).returncode,2)
    def test_starter_expected_red(self):
        d=self.project();r=subprocess.run([sys.executable,'-B','-m','unittest','discover','-s','tests'],cwd=d,text=True,capture_output=True,timeout=8)
        self.assertNotEqual(r.returncode,0);self.assertIn('NotImplementedError',r.stderr)

class TestFixtureGrader(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.ws=Path(self.tmp.name)/'repo';shutil.copytree(ROOT/'fixtures/tiny_repo',self.ws)
    def tearDown(self):self.tmp.cleanup()
    def grade(self):return subprocess.run([sys.executable,'-B',str(ROOT/'tools/grade_fixture.py'),'--workspace',str(self.ws)],capture_output=True,text=True,timeout=12)
    def fix(self):
        p=self.ws/'pagination.py';s=p.read_text();assert 'page_no * size' in s;p.write_text(s.replace('page_no * size','(page_no - 1) * size'))
    def test_original_bug_is_rejected(self):
        r=self.grade();self.assertEqual(r.returncode,1);d=json.loads(r.stdout);self.assertEqual(d['tests']['collected'],9);self.assertGreater(d['tests']['failures'],0)
    def test_real_fix_is_accepted(self):
        self.fix();r=self.grade();self.assertEqual(r.returncode,0,r.stdout);d=json.loads(r.stdout);self.assertEqual(d['tests']['collected'],9);self.assertEqual(d['tests']['errors'],0)
    def test_unrelated_file_change_rejected(self):
        self.fix();(self.ws/'reporting.py').write_text('# tampered');r=self.grade();self.assertEqual(r.returncode,1);self.assertFalse(json.loads(r.stdout)['scope_ok'])
    def test_extra_file_rejected(self):
        self.fix();(self.ws/'success.json').write_text('{"success":true}');self.assertEqual(self.grade().returncode,1)
    def test_missing_workspace_blocked(self):
        shutil.rmtree(self.ws);self.assertEqual(self.grade().returncode,2)

if __name__=='__main__':unittest.main(verbosity=2)
