"""校验教材结构、相对文件链接、课时和Python语法。不会执行应用/付费API，不判学习者成绩。"""
from pathlib import Path
from collections import Counter
import ast,json,re,sys
from urllib.parse import unquote
ROOT=Path(__file__).resolve().parents[1]
def inspect():
    errors=[];m=json.loads((ROOT/'course-manifest.json').read_text(encoding='utf-8'))
    if len(m['order'])!=m['lesson_count'] or len(set(m['order']))!=m['lesson_count']:errors.append('course count/order')
    if set(m['order'])!={p.name for p in (ROOT/'lessons').iterdir() if p.is_dir()}:errors.append('lesson directories differ')
    docs=['00-本课目的与文件导航.md','01-教程.md','02-交给AI.md','03-实验与排错.md','04-复习与迁移答案.md','05-过关卡与代码地图.md']
    for i,l in enumerate(m['order']):
        for n in docs:
            if not (ROOT/'lessons'/l/n).is_file():errors.append(l+'/'+n+' missing')
        if m['lessons'][l]['prerequisite']!=(m['order'][i-1] if i else None):errors.append(l+' prerequisite')
        if not m['lessons'][l]['demo_cases']:errors.append(l+' no demo cases')
    if sum(x['hours'] for x in m['lessons'].values())!=m['lesson_hours']:errors.append('lesson hours')
    if sum(m[x] for x in ['lesson_hours','gate_hours','review_hours'])!=m['total_hours']:errors.append('total hours')
    calendar=m['weeks_plan'];counts=Counter();review=0;gates=0
    if len(calendar)!=m['weeks']:errors.append('calendar length')
    for w in calendar:
        if sum(x['hours'] for x in w['content'])+w['review_hours']!=w['total_hours']:errors.append('weekly hours '+str(w['week']))
        review+=w['review_hours']
        for x in w['content']:
            if x['kind']=='lesson':counts[x['id']]+=x['hours']
            else:gates+=x['hours']
    if counts!={k:v['hours'] for k,v in m['lessons'].items()}:errors.append('calendar lesson allocation')
    if review!=m['review_hours'] or gates!=m['gate_hours']:errors.append('calendar review/gate hours')
    intents=json.loads((ROOT/'lesson-intents.json').read_text(encoding='utf-8'))['lessons']
    if set(intents)!=set(m['order']):errors.append('lesson intent coverage')
    purposes=0
    for lesson in m['order']:
        info=intents[lesson];purpose_count=len(info['topic_questions']);purposes+=purpose_count
        if len(info['topic_headings'])!=purpose_count:errors.append(lesson+' topic questions mismatch')
        tutorial=(ROOT/'lessons'/lesson/'01-教程.md').read_text(encoding='utf-8')
        if tutorial.count('读这一段是为了解决')!=purpose_count:errors.append(lesson+' missing purpose bridges')
        if not (ROOT/info['example']).is_file():errors.append(lesson+' missing actual example')
        for f in info['framework_files']:
            if not (ROOT/f).is_file():errors.append(lesson+' missing framework example '+f)
        directive=(ROOT/'lessons'/lesson/'02-交给AI.md').read_text(encoding='utf-8')
        for marker in ['ANALYZE_ONLY','IMPLEMENT','REVIEW_ONLY','原文锚点','待生成']:
            if marker not in directive:errors.append(lesson+' directive missing '+marker)
        lab=(ROOT/'lessons'/lesson/'03-实验与排错.md').read_text(encoding='utf-8')
        if '<details>' in lab:errors.append(lesson+' answer leak in experiment document')
        if 'prepare_example.py '+lesson not in lab:errors.append(lesson+' missing copy command')
    links=0
    for p in ROOT.rglob('*.md'):
        if '.local' in p.parts:continue
        s=p.read_text(encoding='utf-8')
        # Ignore fenced code before looking for inline Markdown links.
        s=re.sub(r'```.*?```','',s,flags=re.S)
        for target in re.findall(r'\]\(([^)]+)\)',s):
            target=target.split(' "')[0].strip('<>');file=unquote(target.split('#')[0])
            if not file or re.match(r'^[A-Za-z]+:',file):continue
            links+=1
            if not (p.parent/file).resolve().exists():errors.append(str(p.relative_to(ROOT))+': missing '+file)
    py_count=0
    for p in ROOT.rglob('*.py'):
        if '.local' in p.parts:continue
        py_count+=1
        try:ast.parse(p.read_text(encoding='utf-8'),filename=str(p))
        except SyntaxError as e:errors.append(str(p.relative_to(ROOT))+': syntax '+str(e))
    return {'status':'passed' if not errors else 'failed','lessons':m['lesson_count'],'lesson_documents':len(docs)*m['lesson_count'],'total_hours':m['total_hours'],'purpose_bridges_checked':purposes,'local_links_checked':links,'python_files_syntax_checked':py_count,'errors':errors,'scope':'static only; not framework runtime or completed app'}
if __name__=='__main__':
    result=inspect();print(json.dumps(result,ensure_ascii=False,indent=2));sys.exit(0 if result['status']=='passed' else 1)
