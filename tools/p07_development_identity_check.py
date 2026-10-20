"""Real native TLS development identity checks; no formal installer work."""
def check():
    from p07_desktop_fixture import Scenario
    s=Scenario(password='a'*12)
    checks=[]
    def call(action,**fields):
        result=s.call(dict(action=action,**fields))
        assert 'error' not in result,result
        return result['ok']
    try:
        connection=s.connection()
        first=call('connect',connection=connection)
        assert first['role']=='admin' and first['username']=='manager'
        assert not {'token','password'} & first.keys()
        checks.append('default_identity_uses_real_pinned_Host_authentication')
        s.stop_bridge();s.start_bridge()
        restored=call('bootstrap')
        assert restored['automatic'] and restored['session']['subject']==first['subject']
        checks.append('restart_automatically_restores_selected_Host_and_identity')
        snap={'price_version_id':'2026.10.13','lines':[{'line_kind':'normal','product_id':'安装服务','q':'1','h':'','w':'','name':''}]}
        call('calculate',snapshot=snap,draft_revision='1')
        with s.host.service.auth.connection() as c:c.execute('UPDATE sessions SET expires=0')
        receipt=call('submit',snapshot=snap,draft_revision='1',details={'customer':'续接','order_ref':'renewal-single','wechat':''})
        assert receipt['order_id']
        assert s.host.service.ledger.inventory()['counts']['orders']==26
        assert not (s.profile/'pending.bin').exists()
        checks.append('expired_token_renews_once_without_losing_calculation_or_duplicate_order')
        bad={**connection,'certificate_sha256':'0'*64}
        rejected=s.call(dict(action='connect',connection=bad))
        assert rejected['error']['code']=='CERTIFICATE_PIN_MISMATCH'
        assert call('prices')['price_version_id']=='2026.10.13'
        checks.append('wrong_pin_preserves_verified_connection')
        # Durable unknown commits cannot be reassigned to another cached actor.
        call('calculate',snapshot=snap,draft_revision='2')
        s.host.fault.write_text('after_commit',encoding='utf-8')
        unknown=s.call(dict(action='submit',snapshot=snap,draft_revision='2',details={'customer':'','order_ref':'pending-owner','wechat':''}))
        assert unknown['error']['code']=='COMMIT_UNKNOWN'
        s.host.restart()
        rejected=s.call(dict(action='connect',connection=connection,username='sales-one',password=s.host.password))
        assert rejected['error']['code']=='PENDING_IDENTITY_MISMATCH'
        assert (s.profile/'pending.bin').exists()
        call('connect',connection=connection)
        call('recover',retry=True)
        assert s.host.service.ledger.inventory()['counts']['orders']==27
        checks.append('pending_actor_is_immutable_and_original_receipt_recovers_once')
    finally:s.close()
    return {'checks':checks,'sandbox_cleaned':True}
