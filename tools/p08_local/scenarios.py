"""Stop the real server, close/reopen clients, resume in an independent process."""
import time
import sqlite3
from .bridge import Bridge
from .fixture import LocalFixture
from p08_application.wire import identifier


def quote(quantity='1'):
    return dict(price_version_id='fixture-v1', rule_version='business-v1', numeric_profile='numeric-v1',
                lines=[dict(line_kind='normal', product_id='单件', q=quantity, h='', w='', name='')])


def save(client, *, existing=None, quantity='1', ref='offline-D-order', operation_id=None):
    context = dict(snapshot=quote(quantity), sources=[existing['lines'][0]['line_id']] if existing else [None],
                   order_id=existing['order_id'] if existing else None, expected_revision=existing['revision'] if existing else None)
    calculation = client.call('order_preview', **context, draft_revision='1')
    assert calculation['result']['status'] == 'ok', calculation
    result = client.call('save_order', **context, operation_id=operation_id or identifier(), draft_revision='1', details=dict(customer='D-buyer',order_ref=ref,wechat='D-contact'), customer={'customer_id':existing['customer_id']} if existing and existing.get('customer_id') else {})
    return client.call('order',order_id=result['order_id'])


def run(manager_binary, sales_binary=None):
    f = LocalFixture()
    clients = []
    try:
        baseline=f.operation(1)
        f.send(baseline);f.wait(baseline,'applied')
        profile, package = f.package('manager')
        client = Bridge(manager_binary,profile,package); clients.append(client)
        boot = client.call('bootstrap')
        assert boot['session']['role'] == 'admin'
        catalog = client.call('prices')
        assert 'cost' not in catalog['items'][0]
        initial_worker=Bridge(manager_binary,profile,package,worker=True);clients.append(initial_worker)
        deadline=time.monotonic()+45
        while True:
            with sqlite3.connect(profile/'offline.sqlite3') as db:
                cached=db.execute("SELECT count(*) FROM local_orders WHERE id=? AND confirmed IS NOT NULL",(baseline['order_id'],)).fetchone()[0]
            if cached:break
            if time.monotonic()>=deadline:raise RuntimeError('EXISTING_AUTHORIZED_ORDER_NOT_CACHED')
            time.sleep(1)
        initial_worker.close();clients.remove(initial_worker)
        f.host.stop()
        assert client.call('order',order_id=baseline['order_id'])['income_cents']=='1000'
        save_id=identifier()
        one = save(client,operation_id=save_id)
        client.call('note',order_id=one['order_id'],expected_revision=one['revision'],body='durable offline note')
        client.close(); clients.remove(client)
        client = Bridge(manager_binary,profile,package); clients.append(client)
        assert client.call('bootstrap')['session']['subject'] == boot['session']['subject']
        receipt=client.call('local_receipt',operation_id=save_id)
        assert receipt['result']['order_id']==one['order_id']
        replay=save(client,operation_id=save_id)
        assert replay['order_id']==one['order_id']
        saved = client.call('order',order_id=one['order_id'])
        assert saved['notes'][0]['body']=='durable offline note'
        final = save(client,existing=saved,quantity='3')
        assert final['income_cents']=='3000'
        assert final['lines'][0]['line_id']==one['lines'][0]['line_id']
        diff = client.call('order_changes',order_id=one['order_id'],revision=saved['revision'])
        assert any(row['field']=='金额' and row['before']=='1000' and row['after']=='3000' for row in diff['changes'])
        assert 'cost_cents' not in final and 'profit_cents' not in final
        client.close(); clients.remove(client)
        worker=Bridge(manager_binary,profile,package,worker=True); clients.append(worker)
        f.host.start()
        admin=f.host.client('manager')
        deadline=time.monotonic()+90
        while True:
            response=admin.request('GET','/v1/orders?q=offline-D-order&limit=20&offset=0')
            orders=response['orders']
            detail=admin.request('GET','/v1/orders/'+one['order_id']) if orders else None
            if detail and detail['income_cents']=='3000' and len(detail['notes'])==1:
                break
            assert worker.process.poll() is None, 'Worker exited before synchronization'
            if time.monotonic()>=deadline:
                raise RuntimeError('NATIVE_BACKGROUND_UPLOAD_DID_NOT_COMPLETE')
            time.sleep(1)
        assert len(orders)==1 and orders[0]['order_id']==one['order_id']
        assert detail['lines'][0]['line_id']==one['lines'][0]['line_id']
        client=Bridge(manager_binary,profile,package); clients.append(client)
        client.call('bootstrap')
        # Independently inspect durable states; an existing local candidate alone
        # cannot prove the central receipts/feed were incorporated.
        deadline=time.monotonic()+60
        while True:
            with sqlite3.connect(profile/'offline.sqlite3') as db:
                confirmed=db.execute("SELECT count(*) FROM local_orders WHERE confirmed IS NOT NULL AND last_operation IS NULL").fetchone()[0]
                applied=db.execute("SELECT count(*) FROM local_operations WHERE state='applied'").fetchone()[0]
                history=db.execute("SELECT count(*) FROM local_meta WHERE key=?",('diff:'+one['order_id']+':2',)).fetchone()[0]
            if confirmed==2 and applied==3 and history==1:break
            if time.monotonic()>=deadline:raise RuntimeError('CONFIRMED_PROJECTION_OR_HISTORY_NOT_RECEIVED')
            time.sleep(1)
        worker.close();clients.remove(worker)
        f.host.stop()
        cached=client.call('order_changes',order_id=one['order_id'],revision='2')
        assert any(row['field']=='金额' and row['after']=='3000' for row in cached['changes'])
        assert all(row['field'] not in ['成本','利润','K'] for row in cached['changes'])
        f.host.start()
        if sales_binary:
            sales_profile,sales_package=f.package('sales')
            sales=Bridge(sales_binary,sales_profile,sales_package);clients.append(sales)
            assert sales.call('bootstrap')['session']['role']=='sales'
            initial_sales=Bridge(sales_binary,sales_profile,sales_package,worker=True);clients.append(initial_sales)
            deadline=time.monotonic()+45
            while True:
                with sqlite3.connect(sales_profile/'offline.sqlite3') as db:
                    cursor=db.execute("SELECT count(*) FROM local_meta WHERE key='feed_cursor'").fetchone()[0]
                    visible=db.execute('SELECT count(*) FROM local_orders').fetchone()[0]
                if cursor:break
                if time.monotonic()>=deadline:raise RuntimeError('SALES_AUTHORIZED_FEED_NOT_CONSUMED')
                time.sleep(1)
            assert visible==0, 'Sales downloaded another subject orders'
            initial_sales.close();clients.remove(initial_sales)
            assert sales.call('orders',q='',state='',offset=0,view='')['total']==0
            f.host.stop()
            own=save(sales,ref='sales-offline-D')
            assert own['income_cents']=='1000' and own['order_id']!=one['order_id']
            assert 'cost_cents' not in own and 'profit_cents' not in own
            assert sales.call('orders',q='',state='',offset=0,view='')['total']==1
            sales.close();clients.remove(sales)
            sales_worker=Bridge(sales_binary,sales_profile,sales_package,worker=True);clients.append(sales_worker)
            f.host.start()
            admin=f.host.client('manager');deadline=time.monotonic()+60
            while True:
                response=admin.request('GET','/v1/orders?q=sales-offline-D&limit=20&offset=0')
                if response['orders'] and response['orders'][0]['income_cents']=='1000':break
                if time.monotonic()>=deadline:raise RuntimeError('SALES_BACKGROUND_UPLOAD_DID_NOT_COMPLETE')
                time.sleep(1)
        return dict(checks=['real_native_automatic_enrollment_signed_lease_and_public_catalog',
                           'existing_authorized_Host_order_downloaded_and_read_offline',
                           'server_stopped_formal_order_and_note_committed_locally',
                           'client_process_closed_reopened_and_same_order_edited_offline',
                           'lost_local_UI_reply_recovers_same_command_receipt_without_a_second_order',
                           'durable_central_receipts_confirmed_projection_and_bounded_history_cache',
                           'native_business_history_and_financial_projection',
                           'closed_client_independent_worker_uploads_to_restarted_TLS_Host',
                           'stable_order_and_line_IDs_and_single_central_booking'],
                    sales_isolation_executed=bool(sales_binary), order_id=one['order_id'], final_income_cents='3000',
                    live_hosts_contacted=False, final_installers_verified=False)
    finally:
        for c in clients:c.close()
        f.close()
