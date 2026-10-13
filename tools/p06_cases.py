"""Shared P06 shadow inputs and Python reference projection, never copied golden values."""
from dataclasses import asdict
from pathlib import Path
import json
import random
from quote_core import (NormalLine, DiscountLine, PriceItem, PriceSnapshot, QuoteSnapshot,
    DraftDetails, Issue, QuoteSession, OutputBlocked, calculate_quote, parse_price_config,
    refresh_price_config, run_calculation)
from quote_core.numbers import parse_number, parse_percent, decimal_text, ValidationError
ROOT = Path(__file__).resolve().parents[1]
KINDS = ('excel', 'quote_image', 'screenshot')
DRAFT_ID = '5d782c12-60bd-421a-9f12-a3e9fe819d03'

def line(raw):
    d = dict(raw); kind = d.pop('kind')
    return DiscountLine(**d) if kind == 'discount' else NormalLine(**d)

def quote(raw):
    return QuoteSnapshot(raw['price_version_id'], tuple(map(line, raw['lines'])),
                         raw.get('rule_version', 'business-v1'), raw.get('numeric_profile', 'numeric-v1'))

def prices(raw):
    return PriceSnapshot(raw['price_version_id'], tuple(PriceItem(**p) for p in raw['items']))

def line_wire(raw):
    d = asdict(raw); d['kind'] = d.pop('line_kind'); return d

def quote_wire(q):
    return None if q is None else dict(price_version_id=q.price_version_id,
        lines=list(map(line_wire, q.lines)), rule_version=q.rule_version, numeric_profile=q.numeric_profile)

def prices_wire(p):
    return None if p is None else asdict(p) | {'items': [asdict(i) for i in p.items]}

def result_wire(r):
    return dict(status=r.status, rule_version=r.rule_version, numeric_profile=r.numeric_profile,
        price_version_id=r.price_version_id, lines=None if r.lines is None else [dict(
            sequence=l.sequence, raw=line_wire(l.raw), price=None if l.price is None else asdict(l.price),
            normalized=[list(p) for p in l.normalized], amounts=l.amounts.cents_payload(),
            display=l.amounts.display(), subtotal_before_cents=str(l.subtotal_before_cents)) for l in r.lines],
        totals=None if r.totals is None else r.totals.cents_payload(), display=r.display(),
        issues=[asdict(i) for i in r.issues], warnings=[asdict(i) for i in r.warnings])

def config_wire(c):
    return None if c is None else dict(prices=prices_wire(c.prices), source_schema=c.source_schema,
        export_dir=c.export_dir, original_json=c.original_json, screenshot_dir=c.screenshot_dir)

def config_result(r):
    return dict(status=r.status, config=config_wire(r.config), issues=list(map(asdict, r.issues)))

def issue_error(reason, field):
    return dict(status='VALIDATION', issues=[asdict(Issue('VALIDATION', reason, field))])

def payload_wire(p, draft_id):
    return dict(draft_id=draft_id, revision=str(p.revision), snapshot=quote_wire(p.snapshot),
        prices=prices_wire(p.prices), details=asdict(p.details), result=result_wire(p.result))

def decision_wire(d, draft_id):
    return dict(kind=d.kind, status=d.status, allowed=d.allowed,
        payload=None if d.payload is None else payload_wire(d.payload, draft_id), issues=list(map(asdict, d.issues)))

def session_reference(cmd):
    s = QuoteSession(None if cmd.get('snapshot') is None else quote(cmd['snapshot']),
        None if cmd.get('prices') is None else prices(cmd['prices']), details=DraftDetails(**cmd.get('details', {})),
        price_source=cmd.get('price_source', 'unverified'), latest_price_version_id=cmd.get('latest_price_version_id'))
    draft_id = cmd['draft_id']; pending = {}; calls = 0; payloads = []
    def observe(result):
        st = s.state
        state = dict(draft_id=draft_id, revision=str(st.revision),
            calculation_revision=None if st.calculation_revision is None else str(st.calculation_revision),
            status=st.status, snapshot=quote_wire(st.snapshot), prices=prices_wire(st.prices),
            details=asdict(st.details), result=None if st.result is None else result_wire(st.result),
            input_issues=list(map(asdict, st.input_issues)), price_source=st.price_source,
            latest_price_version_id=st.latest_price_version_id, price_confirmation_required=st.price_confirmation_required)
        return dict(state=state, action_result=result, decisions=[decision_wire(s.prepare_output(k), draft_id) for k in KINDS],
                    writer_calls=calls, written_payloads=list(payloads))
    out = [observe(None)]
    for a in cmd['actions']:
        op = a['action']; result = None
        try:
            if op == 'calculate': s.calculate()
            elif op == 'update_inputs': s.update_inputs(quote(a['snapshot']), details=None if a.get('details') is None else DraftDetails(**a['details']))
            elif op == 'update_details': s.update_details(DraftDetails(**a['details']))
            elif op == 'invalidate_inputs': s.invalidate_inputs([Issue(**i) for i in a.get('issues', [])])
            elif op == 'observe_source': s.observe_price_source(a['price_source'], latest_price_version_id=a.get('latest_price_version_id'))
            elif op == 'refresh_prices': s.refresh_prices(prices(a['prices']))
            elif op == 'begin': pending[a['key']] = s.begin_calculation()
            elif op == 'foreign': pending[a['key']] = QuoteSession().begin_calculation()
            elif op == 'apply': result = s.apply_calculation(run_calculation(pending[a['key']]))
            elif op == 'confirm': result = s.confirm_prices(expected_revision=int(a['expected_revision']))
            elif op in ('dispatch', 'writer_error'):
                def writer(p):
                    nonlocal calls
                    calls += 1
                    if op == 'writer_error': raise OSError('synthetic')
                    payload = payload_wire(p, draft_id); payloads.append(payload); return payload
                try: result = dict(status='ok', payload=s.dispatch_output(a['kind'], writer))
                except OutputBlocked as e: result = decision_wire(e.decision, draft_id)
                except OSError: result = dict(status='WRITER_FAILURE')
            else: raise ValueError('unknown action')
        except (TypeError, ValueError, KeyError):
            reason = 'INPUT_ISSUES_TYPE' if op == 'invalidate_inputs' else 'LATEST_PRICE_VERSION_INVALID' if op == 'observe_source' and isinstance(a.get('latest_price_version_id'), str) else 'WIRE_SCHEMA'
            field = 'input_issues' if reason == 'INPUT_ISSUES_TYPE' else 'latest_price_version_id' if reason == 'LATEST_PRICE_VERSION_INVALID' else 'action'
            result = issue_error(reason, field)
        out.append(observe(result))
    return out

def reference(cmd):
    op = cmd['op']
    if op == 'calculate': return result_wire(calculate_quote(quote(cmd['snapshot']), prices(cmd['prices'])))
    if op in ('number', 'percent'):
        try:
            n = parse_percent(cmd['raw']) if op == 'percent' else parse_number(cmd['raw'], field=cmd.get('field',''), empty_k=cmd.get('empty_k', False))
            return dict(status='ok', value=decimal_text(n))
        except ValidationError as e: return issue_error(e.reason, e.field)
    if op == 'config':
        source = bytes(cmd['source_bytes']) if cmd.get('source_bytes') is not None else cmd['source']
        return config_result(parse_price_config(source, price_version_id=cmd['price_version_id'], legacy_single_names=cmd.get('legacy_single_names')))
    if op == 'config_refresh':
        active = None; out = []
        for step in cmd['steps']:
            r = refresh_price_config(active, step['source'], price_version_id=step['price_version_id'], legacy_single_names=step.get('legacy_single_names'))
            active = r.active; out.append(dict(applied=r.applied, active=config_wire(active), validation=config_result(r.validation)))
        return out
    if op == 'session': return session_reference(cmd)
    raise ValueError(op)

def normal(q='1', h='', w='', name=''):
    return dict(kind='normal', product_id='P', q=q, h=h, w=w, name=name)

def snapshot(*lines, version='v1'):
    return dict(price_version_id=version, lines=list(lines) or [normal()], rule_version='business-v1', numeric_profile='numeric-v1')

def catalog(version='v1', sale='10', cost='4', k='', single=True):
    return dict(price_version_id=version, items=[dict(product_id='P', sale=sale, cost=cost, k=k, single=single)])

def document(*items, **metadata):
    return json.dumps(dict(metadata, items=list(items)), ensure_ascii=False)

def item(name='P', **fields):
    return dict(name=name, sale='50', cost='20', single=True) | fields

def cases():
    suite = json.loads((ROOT/'docs/baseline/p01-04-golden.json').read_text(encoding='utf-8'))
    for c in suite['cases']:
        p = c['price_snapshot']; cmd = dict(op='calculate', snapshot=dict(price_version_id=p['price_version_id'], lines=c['input'], rule_version=c['rule_version'], numeric_profile='numeric-v1'), prices=dict(price_version_id=p['price_version_id'], items=[dict(product_id=k, **v) for k,v in p['items'].items()]))
        assert reference(cmd)['display'] == c['expected'], c['id']
        yield 'golden', c['id'], cmd
    rng = random.Random(777)
    import p01_oracle as oracle
    for i in range(200):
        sale, cost = rng.randint(0, 5000), rng.randint(0, 5000)
        p = dict(sale=f'{sale//1000}.{sale%1000:03d}', cost=f'{cost//1000}.{cost%1000:03d}', k='1.123456789012', single=i%2==0)
        ls = [normal(str(rng.randint(0,100)), '1.23','0.45'), dict(kind='discount',percent=str(rng.randint(0,100))), normal('0.123456789012','1','2')]
        cmd=dict(op='calculate',snapshot=snapshot(*ls,version='corpus-v1'),prices=dict(price_version_id='corpus-v1',items=[dict(product_id='P',**p)]))
        independent=oracle.quote(dict(rule_version='business-v1',input=ls,price_snapshot=dict(price_version_id='corpus-v1',items={'P':p})))
        assert reference(cmd)['display'] == {k:independent[k] for k in ('status','lines','totals')}
        yield 'rational_corpus', str(i), cmd
    expressions=['1/3*3','(0-5)%3','(5)%(0-3)+3','0.0050000000000','(1e9*1e9*1e9*1e9*1e9)%3','￥（10＋5）元','2米×3m','12.5%']
    expressions += [f'({a}/{b})*{b}' for a in range(1,10) for b in range(2,10)]
    expressions += [True,False,1.5,None,'True','False','NaN','Infinity','1/0','1%0','abs(1)','2**2',"__import__('os')",' '*257,'1+'*41+'1','-'*18+'1','1e999999999','1e-13','0.0000000000001','1e9*1e9*1e9*1e9*1e9*1e9','元','-0','1+'*21+'1','(1/3)*(1/3)','1\n+2','1+\t2','1_000','01','00','2//0','(3/1000000000000)/2','0.000000000003/2','1#comment','1\\\n+2']
    for i,raw in enumerate(expressions): yield 'numbers',str(i),dict(op='number',raw=raw,field='q')
    for i,raw in enumerate(['',' '*256,' '*257]): yield 'empty_k',str(i),dict(op='number',raw=raw,field='k',empty_k=True)
    for i,raw in enumerate(['88.555555555555%','100','0','90％','９０％','٩٠%','𝟡𝟘%','1+2','',101,'101','-1','nan',True,'88.5555555555555','1e2','.5','50%%']): yield 'percent',str(i),dict(op='percent',raw=raw)
    # Native declared limits, not monkey-patched lower test limits.
    for count in [0,10000,10001]:
        q=snapshot();q['lines']=[normal('0')]*count
        yield 'core_limits',str(count),dict(op='calculate',snapshot=q,prices=catalog())
    for i,(q,p) in enumerate([(snapshot(normal('1',name='折扣'),dict(kind='discount',percent='90',name='普通项目')),catalog()),(snapshot(),catalog(sale='1',cost='4')),(snapshot(),dict(price_version_id='v1',items=catalog()['items']+catalog()['items'])),(snapshot(),dict(price_version_id='v1',items=catalog()['items']+[dict(product_id='unused',sale='',cost='',k='',single=False)])),(snapshot(),catalog(single='false')),(snapshot(version='v2'),catalog()),(snapshot(),catalog(sale='999999999',cost='0',single=False))]):
        yield 'core_edges',str(i),dict(op='calculate',snapshot=q,prices=p)
    q=snapshot(normal('922337203.6854775807'));p=catalog(sale='100000000',cost='0')
    yield 'json_integer_precision','i64-max',dict(op='calculate',snapshot=q,prices=p)
    configs=[document(item(),export_dir=r'relative\利润表',screenshot_dir=r'图片'),document(item('面积',sale='2+3元',k='1.5倍',single=False),item('单件',sale='0.005',cost='0')),'{"架":[50,20,""],"板":["3.5",1,"1"],"export_dir":"E:\\\\利润表"}','[]','true','1','"text"','{}','{"items":[]}','{"export_dir":""}','{"items":[],"items":[]}','{"P":[1,0,1],"P":[2,0,1]}','{"items":[{"name":"P","sale":1,"sale":2,"cost":0}]}','{"items":[{"name":"P","sale":999999999.999999999999,"cost":0.123456789012,"single":true}]}','{"items":[{"name":"P","sale":1e999,"cost":0}]}','['*33+']'*33,'{"items":[{"name":"P","sale":'+'1'*257+',"cost":0}]}','{"客户机密": broken}','','broken',None,False,{},document(item('A'),item(' A ')),document(item('折扣')),document(item('items'),item('export_dir')),json.dumps({'items':[item('\ud800')]}), '\ufeff'+document(item('中文')).replace('{','{\r\n',1)]
    for val in [None,False,1,[],'item']: configs.append(document(item(),val))
    for val in [{},None,False,'bad']:configs.append(json.dumps({'items':val,'P':[1,2,3]}))
    for f in ['name','sale','cost']:
        d=item();del d[f];configs.append(document(d))
    configs.extend([document(item(),hidden={'ignored':1}),document(item('Q',hidden='ignored'))])
    for flag in ['single','qty_only']:
        for value in ['false','true',0,1,None,True,False]:
            d=dict(name='P',sale='1',cost='0');d[flag]=value;configs.append(document(d))
    configs.extend([document(item(single=False,qty_only=True)),document(item(single=True,qty_only=True)),document(dict(name='P',sale=1,cost=0)),document(item('bad\n')),document(item('bad\x00')),document(item('P'*257))])
    for field in ['sale','cost','k']:
        for value in [True,None,[], '', '-1','1/0','1e10','0.0000000000001','nan','__import__("os")','1e9*1e9*1e9*1e9*1e9*1e9']:
            configs.append(document(item(**{field:value})))
    for value in [True,12,None,'   ']:configs.append(document(item(value)))
    for field in ['export_dir','screenshot_dir']:
        for value in [False,12,None,'bad\x00','P'*32768]:configs.append(document(item(),**{field:value}))
    configs.append(' '*1048577)
    configs.append(document(*(item(str(i)) for i in range(10001))))
    for i,source in enumerate(configs): yield 'config',str(i),dict(op='config',source=source,price_version_id='v1')
    for i,source in enumerate([b'\xff',document(item('中文')).encode('gbk'), ('\ufeff'+document(item('中文'))).encode('utf-8')]):yield 'config_encoding',str(i),dict(op='config',source=None,source_bytes=list(source),price_version_id='v1')
    for i,v in enumerate([None,True,'',' v1 ','V'*257]):yield 'config_version',str(i),dict(op='config',source=document(item()),price_version_id=v)
    for i,source in enumerate(['{"架":[50,20,""],"板":["3.5",1,"1"]}', '{"A":[1,0,1]," A ":[1,0,1]}']+[json.dumps({'P':v}) for v in [[1,2],[1,2,3,4],{},None,False,'1']]):
        for j,policy in enumerate([[],['架'],['折扣']]):yield 'config_legacy',f'{i}-{j}',dict(op='config',source=source,price_version_id='v1',legacy_single_names=policy)
    yield 'config_refresh','retain-and-replace',dict(op='config_refresh',steps=[dict(source=s,price_version_id=v) for s,v in [(document(item(),export_dir='原目录').replace('"items":','\r\n"items":'),'v1'),('broken','v2'),(document(item('Q'),None),'v2'),(document(item('Q'),export_dir=''),'v2')]])
    yield 'config_refresh','no-previous',dict(op='config_refresh',steps=[dict(source='broken',price_version_id='v1')])
    yield from session_cases()

def session_cases():
    calc=dict(action='calculate');begin=dict(action='begin',key='old')
    dispatch=[dict(action='dispatch',kind=k) for k in KINDS]
    def scenario(name, actions, **fields):
        cmd=dict(op='session',draft_id=DRAFT_ID,snapshot=snapshot(),prices=catalog(),price_source='current',latest_price_version_id='v1',actions=actions)|fields
        return 'session',name,cmd
    yield scenario('uncalculated-then-three-outputs',[*dispatch,calc,*dispatch], details=dict(customer='000012',order_ref='00003',wechat='微信'))
    yield scenario('no-source',[calc,*dispatch],price_source='unverified',latest_price_version_id=None)
    yield scenario('no-snapshot',[calc,*dispatch],snapshot=None)
    yield scenario('no-prices',[*dispatch,calc,*dispatch],prices=None)
    yield scenario('partial-error',[calc,*dispatch],snapshot=snapshot(normal(),normal('bad')))
    yield scenario('invalid-discount',[calc,*dispatch],snapshot=snapshot(normal(),dict(kind='discount',percent=True)))
    yield scenario('zero-discount-and-loss',[calc,*dispatch],snapshot=snapshot(dict(kind='discount',percent='90'),normal(),dict(kind='discount',percent='0')),prices=catalog(sale='1',cost='4'))
    yield scenario('half-cent-and-text',[calc,*dispatch],snapshot=snapshot(normal(),normal()),prices=catalog(sale='0.005',cost='0'),details=dict(customer='000012',order_ref='00003',wechat='微信'))
    yield scenario('inputs-ABA',[calc,*dispatch,begin,dict(action='update_inputs',snapshot=snapshot(normal('2'))),*dispatch,calc,dict(action='apply',key='old'),dict(action='update_inputs',snapshot=snapshot()),dict(action='apply',key='old'),*dispatch,calc,*dispatch])
    yield scenario('metadata-and-capture',[calc,begin,dict(action='update_details',details=dict(customer='乙',order_ref='00002',wechat='新微信')),*dispatch,dict(action='apply',key='old'),calc,dict(action='invalidate_inputs',issues=[asdict(Issue('VALIDATION','SNAPSHOT_TEXT_TYPE','q',2))]),*dispatch,calc,dict(action='update_inputs',snapshot=snapshot()),calc,*dispatch])
    actions=[calc]
    for source in ['unavailable','unverified','invalid','current']:
        actions.extend([dict(action='observe_source',price_source=source,latest_price_version_id='v1'),*dispatch,calc,*dispatch])
    yield scenario('sources',actions)
    yield scenario('versions-never-rebind',[calc,dict(action='observe_source',price_source='current',latest_price_version_id='v2'),*dispatch,calc,*dispatch,dict(action='observe_source',price_source='current',latest_price_version_id='v1'),*dispatch,calc,dict(action='observe_source',price_source='current',latest_price_version_id='v1'),*dispatch])
    yield scenario('refresh-confirm',[calc,*dispatch,dict(action='observe_source',price_source='current',latest_price_version_id='v2'),calc,*dispatch,dict(action='refresh_prices',prices=catalog('v2',sale='12')),dict(action='confirm',expected_revision='2'),calc,*dispatch,dict(action='confirm',expected_revision='0'),dict(action='confirm',expected_revision='2'),*dispatch])
    yield scenario('same-version-refresh',[calc,dict(action='refresh_prices',prices=catalog(sale='15')),*dispatch,calc,*dispatch,dict(action='confirm',expected_revision='1'),dict(action='update_inputs',snapshot=snapshot(normal('2'))),calc,*dispatch])
    yield scenario('late-cross-draft-invalid',[calc,begin,dict(action='update_inputs',snapshot=snapshot(normal('2'))),calc,dict(action='apply',key='old'),dict(action='foreign',key='foreign'),dict(action='apply',key='foreign'),dict(action='update_inputs',snapshot=snapshot(normal('bad'))),calc,dict(action='apply',key='old'),*dispatch])
    yield scenario('writer-failure-and-recheck',[calc,dict(action='writer_error',kind='excel'),dict(action='invalidate_inputs'),*dispatch,dict(action='update_inputs',snapshot=snapshot()),calc,*dispatch])
    yield scenario('bad-actions-atomic',[calc,dict(action='update_details',details=dict(customer=123)),dict(action='observe_source',price_source=True),dict(action='observe_source',price_source='current',latest_price_version_id=' v1 '),dict(action='invalidate_inputs',issues=[asdict(Issue('WARNING','X','q'))]),dict(action='dispatch',kind='draft_screenshot'),*dispatch])
