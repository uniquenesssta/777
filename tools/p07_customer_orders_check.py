"""P07-07 real native IPC + Rust HTTPS checks using owned synthetic files."""
import argparse,json,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests'),str(ROOT/'tools')]
from p07_desktop_fixture import Scenario
from quote_service.journal import MemoryJournal

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    checks=[];scenario=None
    try:
        scenario=Scenario()
        def call(action,**data):
            r=scenario.call(dict(action=action,**data))
            assert 'error' not in r,r
            return r['ok']
        call('bootstrap');call('connect',connection=scenario.connection(),username='manager',password=scenario.host.password)
        groups=call('customer_orders',query='00000',offset=0,group_id=None,order_offset=0)
        assert groups['total']==1 and len(groups['groups'][0]['orders'])==1,groups
        old=call('order',order_id=groups['groups'][0]['orders'][0]['order_id'])
        context=dict(order_id=old['order_id'],expected_revision=str(old['revision']),sources=[old['lines'][0]['line_id'],None],snapshot=dict(price_version_id='2026.10.13',rule_version='business-v1',numeric_profile='numeric-v1',lines=[old['lines'][0]['raw'],old['lines'][0]['raw']]))
        preview=call('order_preview',**context,draft_revision='10');assert preview['result']['totals']['income_cents']=='20000'
        saved=call('save_order',**context,draft_revision='10',details=old['details'],customer={});assert saved['order_id']==old['order_id'] and str(saved['revision'])=='2'
        current=call('order',order_id=old['order_id']);assert len(current['history'])==1 and current['income_cents']=='20000'
        checks.append('native_preview_save_same_order_with_revision_and_history')
        for revision,quantity,income in [(2,'2','30000'),(3,'3','40000')]:
            lines=[l['raw'].copy() for l in current['lines']];lines[0]['q']=quantity
            context=dict(order_id=old['order_id'],expected_revision=str(current['revision']),sources=[l['line_id'] for l in current['lines']],snapshot=dict(price_version_id='2026.10.13',rule_version='business-v1',numeric_profile='numeric-v1',lines=lines))
            call('order_preview',**context,draft_revision=str(revision+10))
            receipt=call('save_order',**context,draft_revision=str(revision+10),details=current['details'],customer={'customer_id':current['customer_id']})
            current=call('order',order_id=old['order_id'])
            assert str(receipt['revision'])==str(revision+1) and current['income_cents']==income and len(current['history'])==revision
        checks.append('native_repeated_edits_use_latest_revision_line_sources_and_exact_history')
        details={**old['details'],'order_ref':'独立订单00002'}
        context=dict(order_id=None,expected_revision=None,sources=[None],snapshot=dict(price_version_id='2026.10.13',rule_version='business-v1',numeric_profile='numeric-v1',lines=[old['lines'][0]['raw']]))
        call('order_preview',**context,draft_revision='11');new=call('save_order',**context,draft_revision='11',details=details,customer={'customer_id':current['customer_id']})
        groups=call('customer_orders',query=old['details']['customer'],offset=0,group_id=current['customer_id'],order_offset=0)
        assert groups['total']==1 and groups['groups'][0]['total']==2 and groups['groups'][0]['totals']['income_cents']=='50000',groups
        assert new['order_id']!=old['order_id'];checks.append('native_separate_order_number_same_customer_exact_aggregate')
        year=time.strftime('%Y');job=call('create_report',**{'from':year+'-01-01','to':year+'-12-31'})
        deadline=time.monotonic()+45
        while True:
            record=next(j for j in call('outputs')['jobs'] if j['job_id']==job['job_id'])
            if record['state']=='done':break
            assert record['state']!='failed' and time.monotonic()<deadline,record
            time.sleep(.1)
        assert record['kind']=='excel_period' and record['range']['from']==year+'-01-01'
        import base64
        content=scenario.host.client('manager').request('GET','/v1/outputs/'+job['job_id']+'/content')
        (args.output/'P07-07-readable-example.xlsx').write_bytes(base64.b64decode(content['data_base64'],validate=True))
        opened=scenario.call(dict(action='open_output_folder',job_id=job['job_id']))
        if os.name=='nt':assert 'error' not in opened,opened
        else:assert opened.get('error',{}).get('code')=='WINDOWS_REQUIRED',opened
        checks.append('native_period_report_completed_and_actual_folder_action' if os.name=='nt' else 'native_period_report_completed_folder_correctly_requires_Windows')
        scenario.stop_bridge();scenario.start_bridge();call('bootstrap');call('connect',connection=scenario.connection(),username='manager',password=scenario.host.password)
        assert call('order',order_id=old['order_id'])['income_cents']=='40000';checks.append('native_restart_keeps_edited_order')
        (args.output/'report.json').write_text(json.dumps(dict(task='P07-07',platform=os.name,checks=checks,status='passed',production_paths_accessed=False),ensure_ascii=False,indent=2))
        print(json.dumps(dict(status='passed',checks=checks),ensure_ascii=False))
    finally:
        if scenario:scenario.close()
if __name__=='__main__':main()
