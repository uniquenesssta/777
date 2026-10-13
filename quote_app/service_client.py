"""Opt-in service mode for the existing Tk layouts; network workers never use Tk."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import ssl
import threading
from tkinter import filedialog,messagebox,simpledialog,ttk
import uuid

from quote_core import DraftDetails,capture_legacy_quote,Amounts
from quote_core.numbers import money_text
from quote_service.client import Client,CommitUnknown,connection_settings
from quote_service.journal import Journal
from quote_service.protocol import APIError,decode
from quote_ledger.backup import publish_json
from quote_files.configuration import save_config
from quote_files.transactions import digest,read_bytes
from .jobs import Jobs,QueueFull
from .integration import QuoteApplicationMixin
from .connections import ConnectionMixin


class ServiceApplicationMixin:
    def initialize_background_io(self):
        from .background import configure_ui_thread_scheduling
        configure_ui_thread_scheduling()
        self.default_items=[]  # No default/legacy price or cost source in service mode.
        self._io_runtime=None
        self._svc_jobs=Jobs(timeout=15);self._svc_callbacks={};self._svc_owner=threading.get_ident()
        self._svc_closing=False;self._svc_client=None;self._svc_prices=None;self._svc_result=None
        self._svc_submitted=None
        self._svc_snapshot=None;self._svc_details=None;self._svc_confirmed=True;self._svc_orders={}
        self._svc_preferences=None;self._svc_token_epoch=0;self._svc_view=None
        self._svc_price_diff='当前没有价格差异。'
        self._svc_journal=Journal(Path(self.service_settings_file).with_suffix('.pending.bin')) if not hasattr(self,'_svc_journal') else self._svc_journal
        self.background_status_var=self._new_text_var('服务客户端就绪，请登录')
        self._svc_poll_job=self.root.after(40,self._service_poll)
        self._svc_settings_poll=self.root.after(30000,self._observe_service_settings)

    def apply_window_icon(self):
        pass  # Service launch never probes the legacy resource/share paths.

    def initialize_quote_state(self):
        QuoteApplicationMixin.initialize_quote_state(self)

    def initialize_connections(self):
        ConnectionMixin._initialize_connection_fields(self)
        self.storage_status_var.set('服务连接未应用，请核对服务器证书后登录。')
        self.data_root='HTTPS service'
        self.service_address=self._new_text_var('');self.service_certificate=self._new_text_var('');self.service_username=self._new_text_var('')
        self.service_password=self._new_text_var('');self._svc_pin=''
        self._svc_profile_hash=None;self._svc_profile_bad=False
        path=Path(self.service_settings_file)
        if path.exists():
            try:
                raw=path.read_bytes();settings=connection_settings(decode(raw));self._svc_profile_hash=digest(raw)
                self.service_address.set(settings['url']);self.service_certificate.set(settings['certificate'])
                self.service_username.set(settings['username']);self._svc_pin=settings['certificate_sha256']
            except Exception:self._svc_profile_bad=True;self.set_feedback('本机服务连接配置不可用，原件保留。',is_error=True)

    def install_background_controls(self):
        box=ttk.Frame(self.root,padding=6);box.pack(side='bottom',fill='x')
        ttk.Label(box,textvariable=self.background_status_var).pack(side='left')
        ttk.Button(box,text='取消读取',command=self.cancel_background_reads).pack(side='right')

    def install_quote_controls(self):
        for var in (self.user_name,self.order_no,self.wechat_no):var.trace_add('write',self.quote_input_changed)
        self.quote_status_var=self._new_text_var('请连接服务并登录')
        box=ttk.Frame(self.calc_page,padding=6);box.pack(fill='x')
        ttk.Label(box,textvariable=self.quote_status_var).pack(side='left',expand=True,fill='x')
        ttk.Button(box,text='确认当前价格',command=self.confirm_current_prices).pack(side='right')
        ttk.Button(box,text='查看价格差异',command=self.show_price_changes).pack(side='right')
        if hasattr(self,'calc_export_button'):self.calc_export_button.configure(text='提交订单',command=self.export_to_excel)
        self.notebook.tab(self.excel_page,text='服务账本')
        self.notebook.select(self.excel_page)
        self.update_quote_status()

    def setup_excel_page(self):
        wrapper=ttk.Frame(self.excel_page,padding=10);wrapper.pack(fill='both',expand=True)
        connection=ttk.LabelFrame(wrapper,text='服务连接（用户名是操作人员身份）',padding=8);connection.pack(fill='x')
        for row,(label,var,secret) in enumerate((('HTTPS地址',self.service_address,False),('服务器公开证书',self.service_certificate,False),('用户名',self.service_username,False),('密码',self.service_password,True))):
            ttk.Label(connection,text=label).grid(row=row,column=0,sticky='w')
            ttk.Entry(connection,textvariable=var,show='●' if secret else '').grid(row=row,column=1,sticky='ew')
        ttk.Button(connection,text='选择证书',command=self.choose_service_certificate).grid(row=1,column=2)
        ttk.Button(connection,text='登录',command=self.login_service).grid(row=4,column=0)
        ttk.Button(connection,text='退出登录',command=self.logout_service).grid(row=4,column=1,sticky='w')
        ttk.Label(connection,textvariable=self.storage_status_var).grid(row=5,column=0,columnspan=3,sticky='w')
        connection.columnconfigure(1,weight=1)
        paths=ttk.LabelFrame(wrapper,text='输出位置（由母版发布，子版只读继承）',padding=6);paths.pack(fill='x',pady=6)
        self.service_directory_entries={}
        for row,(name,var) in enumerate((('Excel目录',self.export_dir_var),('图片目录',self.screenshot_dir_var))):
            ttk.Label(paths,text=name).grid(row=row,column=0)
            entry=ttk.Entry(paths,textvariable=var,state='normal' if self.quote_role=='manager' else 'readonly')
            entry.grid(row=row,column=1,sticky='ew');self.service_directory_entries[name]=entry
        paths.columnconfigure(1,weight=1)
        if self.quote_role=='manager':
            ttk.Button(paths,text='发布输出目录',command=self.apply_export_dir).grid(row=2,column=0)
            ttk.Button(paths,text='创建账号',command=self.create_service_account).grid(row=2,column=1,sticky='w')
            ttk.Button(paths,text='备份状态',command=self.show_service_backup).grid(row=2,column=2)
            ttk.Button(paths,text='管理账号',command=self.manage_service_accounts).grid(row=3,column=0)
            ttk.Button(paths,text='备份计划',command=self.edit_service_backup_plan).grid(row=3,column=1,sticky='w')
            ttk.Button(paths,text='立即备份',command=self.run_service_backup).grid(row=3,column=2)
        actions=ttk.Frame(wrapper);actions.pack(fill='x')
        for label,command in [('刷新订单',self.refresh_excel_files),('查看订单',self.load_current_excel_sheet),('追加备注',self.save_current_excel_remark),('核查上次提交',self.check_last_write),('按原请求重试',self.retry_service_request)]:
            ttk.Button(actions,text=label,command=command).pack(side='left',padx=2)
        if self.quote_role=='manager':
            ttk.Button(actions,text='作废',command=self.delete_current_excel_row).pack(side='left')
            ttk.Button(actions,text='恢复',command=self.restore_current_excel_order).pack(side='left')
        output_actions=ttk.Frame(wrapper);output_actions.pack(fill='x')
        for label,command in [('导出Excel',lambda:self.request_service_output('excel_quote')),('生成报价图片',lambda:self.request_service_output('quote_png')),('输出任务',self.show_output_tasks)]:
            ttk.Button(output_actions,text=label,command=command).pack(side='left',padx=2)
        if self.quote_role=='manager':ttk.Button(output_actions,text='内部明细（私有）',command=lambda:self.request_service_output('excel_admin')).pack(side='left')
        self._svc_search=self._new_text_var('')
        ttk.Entry(output_actions,textvariable=self._svc_search,width=20).pack(side='left',padx=6)
        ttk.Button(output_actions,text='搜索客户/订单号',command=self.refresh_excel_files).pack(side='left')
        columns=('order_id','time','external_order','income','state','revision')
        if self.quote_role=='manager':columns+=('cost','profit')
        self.service_order_tree=ttk.Treeview(wrapper,columns=columns,show='headings',height=10,selectmode='browse')
        for col in columns:self.service_order_tree.heading(col,text={'order_id':'订单ID','time':'时间','external_order':'客户订单号','income':'收入','cost':'成本','profit':'利润','state':'状态','revision':'版本'}[col])
        self.service_order_tree.pack(fill='both',expand=True)
        self.service_order_tree.bind('<Double-1>',lambda event:self.load_current_excel_sheet())
        self.service_detail_var=self._new_text_var('选择服务订单查看明细与追加备注')
        ttk.Label(wrapper,textvariable=self.service_detail_var,wraplength=1050).pack(fill='x')
        from tkinter.scrolledtext import ScrolledText
        self.service_detail_text=ScrolledText(wrapper,height=7,state='disabled',wrap='word');self.service_detail_text.pack(fill='both',expand=True)
        page=ttk.Frame(wrapper);page.pack(fill='x')
        self._svc_offset=0
        ttk.Button(page,text='上一页',command=lambda:self._service_page(-100)).pack(side='left')
        ttk.Button(page,text='下一页',command=lambda:self._service_page(100)).pack(side='left')

    def _service_page(self,delta):
        self._svc_offset=max(0,self._svc_offset+delta);return self.refresh_excel_files(page=True)

    def _service_submit(self,channel,action,callback,*,write=False,fresh=False):
        if threading.get_ident()!=self._svc_owner:raise RuntimeError('仅主线程可操作服务界面')
        if self._svc_closing:return False
        revision=self.quote_session.state.revision;epoch=self._svc_token_epoch
        try:task=self._svc_jobs.submit(channel,lambda context:action(),write=write)
        except QueueFull as exc:self.set_feedback(str(exc),is_error=True);return False
        self._svc_callbacks[task.number]=(callback,revision,epoch,fresh)
        self.background_status_var.set('请求处理中，可继续编辑草稿')
        return task

    def _service_poll(self):
        for task,state,value in self._svc_jobs.drain():
            delivery=self._svc_callbacks.get(task.number)
            if not delivery:continue
            if state=='timeout':
                self.set_feedback('等待超时；写入结果未确认时请保留原请求并核查。',is_error=True);continue
            self._svc_callbacks.pop(task.number,None)
            callback,revision,epoch,fresh=delivery
            if not task.write and (not self._svc_jobs.current(task) or epoch!=self._svc_token_epoch or self._svc_closing):continue
            if state=='failed':
                self.set_feedback(('请求结果未确认，请核查上次提交。' if isinstance(value,CommitUnknown) else '请求失败：'+str(value)),is_error=True)
                if isinstance(value,APIError) and value.status==401:self._svc_result=None;self._storage_valid=False
                if isinstance(value,APIError) and value.code=='QUERY_VIEW_CHANGED':
                    self._svc_offset=0;self._svc_view=None;self.set_feedback('账本已更新，请点刷新订单重新查看。',is_error=True)
                if task.channel=='calculate':self._svc_result=None
            elif state=='completed':
                if not fresh or revision==self.quote_session.state.revision:
                    try:callback(value)
                    except Exception as exc:self.set_feedback('结果已返回，界面更新失败：'+str(exc),is_error=True)
                else:self.set_feedback('输入已变化，请重新计算；旧结果未覆盖新草稿。')
            self.update_quote_status()
        if self._svc_closing and not self._svc_jobs.writing:
            self._svc_jobs.close();self.root.destroy();return
        self._svc_poll_job=self.root.after(40,self._service_poll)

    def choose_service_certificate(self):
        path=filedialog.askopenfilename(parent=self.root,filetypes=[('公开证书','*.pem')])
        if path:
            fingerprint=hashlib.sha256(ssl.PEM_cert_to_DER_cert(Path(path).read_text(encoding='ascii'))).hexdigest()
            if messagebox.askyesno('确认服务器身份','请与主机提供的指纹核对：\n'+fingerprint):
                self.service_certificate.set(path);self._svc_pin=fingerprint

    def login_service(self):
        if self._svc_jobs.writing:return False
        secret=self.service_password.get();self.service_password.set('')
        try:
            settings=connection_settings({'schema':'777-service-client-v1','url':self.service_address.get().strip(),'certificate':self.service_certificate.get(),
                                         'certificate_sha256':self._svc_pin,'username':self.service_username.get()})
            client=Client(settings)
        except Exception as exc:self.set_feedback('连接未确认：'+str(exc),is_error=True);return False
        expected='admin' if self.quote_role=='manager' else 'sales'
        def login():
            if self._svc_profile_bad:raise APIError(409,'CLIENT_CONFIG_REQUIRES_REVIEW')
            identity=client.login(settings['username'],secret)
            if identity['role']!=expected:client.logout();raise APIError(403,'ROLE_DOES_NOT_MATCH_CLIENT')
            config=Path(self.service_settings_file);config.parent.mkdir(parents=True,exist_ok=True)
            save_config(config,json.dumps(settings,ensure_ascii=False).encode('utf-8'),expected_hash=self._svc_profile_hash,
                        validator=lambda raw:connection_settings(decode(raw)))
            return client
        def ready(value):
            previous=self._svc_client
            self._svc_orders={};self.service_order_tree.delete(*self.service_order_tree.get_children())
            self.service_detail_text.configure(state='normal');self.service_detail_text.delete('1.0','end');self.service_detail_text.configure(state='disabled')
            self.service_detail_var.set('请重新选择当前账号的订单。')
            if previous and previous.subject!=value.subject:
                for var in (self.user_name,self.order_no,self.wechat_no):var.set('')
                for row in self.calc_rows:
                    for field in ('q','h','w'):
                        if field in row:row[field].set('')
            self._svc_client=value;self._svc_token_epoch+=1;self._storage_valid=True
            self.storage_status_var.set('已连接：'+settings['url']+'；身份：'+settings['username'])
            self._svc_profile_hash=digest(read_bytes(self.service_settings_file))
            self.set_feedback('已登录：'+settings['username']+'。销售账本仅显示本人订单。')
            self.reload_price_settings_from_json(first_load=True);self.refresh_excel_files()
        return self._service_submit('login',login,ready,write=True)

    def logout_service(self):
        client=self._svc_client
        if not client or self._svc_jobs.writing:return False
        def done(value):
            self._svc_client=None;self._svc_token_epoch+=1;self._storage_valid=False;self._svc_result=None
            self.storage_status_var.set('已退出登录。')
            self._svc_prices=None;self._svc_orders={};self.service_order_tree.delete(*self.service_order_tree.get_children())
            self.service_detail_var.set('已退出登录');self.clear_quote_display()
            self.service_detail_text.configure(state='normal');self.service_detail_text.delete('1.0','end');self.service_detail_text.configure(state='disabled')
            for var in (self.user_name,self.order_no,self.wechat_no):var.set('')
            for row in self.calc_rows:
                for field in ('q','h','w'):
                    if field in row:row[field].set('')
        return self._service_submit('logout',client.logout,done,write=True)

    def _require_client(self):
        if not self._svc_client or not self._storage_valid:raise APIError(401,'请先登录服务')
        return self._svc_client

    def load_settings_to_ui(self):return False
    def _observe_price_file(self):return self._svc_prices
    def observe_storage(self):return self._storage_valid
    def ensure_directories(self):return None
    def _read_price_candidate(self):raise APIError(403,'服务模式不读取共享价格文件')
    def get_report_excel_paths(self):raise APIError(403,'服务模式通过账本接口查询')
    def browse_excel_file(self):self.set_feedback('服务账本请使用订单列表查询。')
    def delete_excel_path(self,path):raise APIError(403,'服务模式禁止裸删报表文件')
    def _write_quote_excel(self,*args):raise APIError(403,'服务模式禁止裸写Excel')
    def save_screenshot(self):return self.request_service_output('quote_png',current=True)
    def save_quote_image(self):return self.save_screenshot()

    def _price_mapping(self):
        if not self._svc_prices:raise APIError(409,'请先刷新已发布价格')
        return {p['product_id']:{'sale':p['sale'],'cost':p.get('cost','0'),'k':p['k'],'single':p['single']} for p in self._svc_prices['items']}

    def reload_price_settings_from_json(self,silent=False,first_load=False):
        if not self._svc_client:return False
        client=self._svc_client
        def loaded(values):
            prices,preferences=values;old=self._svc_prices
            if old and old['price_version_id']!=prices['price_version_id']:self._svc_confirmed=False
            previous={p['product_id']:p for p in old['items']} if old else {}
            changes=[]
            for p in prices['items']:
                before=previous.pop(p['product_id'],None)
                if before!=p:changes.append(p['product_id']+'：'+('新增' if before is None else '；'.join(f'{key} {before.get(key)} → {p[key]}' for key in p if key!='product_id' and before.get(key)!=p[key])))
            changes.extend(name+'：已移除' for name in previous)
            self._svc_price_diff='\n'.join(changes) or '当前没有价格差异。'
            self._svc_prices=prices;self._svc_result=None;self._svc_preferences=preferences
            self._loading_prices=True
            try:
                for row in self.setting_rows:
                    if row.get('frame') is not None:row['frame'].destroy()
                self.setting_rows=[]
                for p in prices['items']:self.add_setting_row(p['product_id'],p['sale'],p.get('cost','0'),p['k'],p['single'])
            finally:self._loading_prices=False
            self.last_config_snapshot=self._price_mapping();self.refresh_item_selector();self.update_calc_row_states(self.last_config_snapshot)
            self.export_dir_var.set(preferences['export_dir']);self.screenshot_dir_var.set(preferences['image_dir'])
            self.quote_input_changed();self.set_feedback('服务价格与母版输出目录已载入。')
        return self._service_submit('prices',lambda:(client.request('GET','/v1/prices'),client.request('GET','/v1/settings')),loaded)

    def _observe_service_settings(self):
        if self._svc_closing:return
        if self._svc_client:
            client=self._svc_client
            def apply(value):
                old=self._svc_preferences
                if self.quote_role=='manager' and old and (self.export_dir_var.get()!=old['export_dir'] or self.screenshot_dir_var.get()!=old['image_dir']):return
                self._svc_preferences=value;self.export_dir_var.set(value['export_dir']);self.screenshot_dir_var.set(value['image_dir'])
            self._service_submit('directory_observation',lambda:client.request('GET','/v1/settings'),apply)
        self._svc_settings_poll=self.root.after(30000,self._observe_service_settings)

    def quote_input_changed(self,*args):
        if getattr(self,'_loading_prices',False):return
        if hasattr(self,'quote_session'):self.quote_session.invalidate_inputs()
        self._svc_result=None
        self._svc_submitted=None
        if hasattr(self,'total_val'):self.clear_quote_display()
        self.update_quote_status()

    def update_quote_status(self):
        if hasattr(self,'quote_status_var'):
            self.quote_status_var.set('已计算，可以提交订单。' if self._svc_result and self._svc_confirmed and self._storage_valid else '请登录、刷新价格并计算；价格变更后需确认。')

    def calculate(self,notify=True):
        try:
            client=self._require_client();snapshot,_=capture_legacy_quote(self.calc_rows,self._price_mapping(),price_version_id=self._svc_prices['price_version_id'])
            if self.quote_role=='manager' and QuoteApplicationMixin.get_settings_snapshot(self)[0]!=self._price_mapping():raise APIError(409,'请先发布修改后的价格')
            details=DraftDetails(self.user_name.get(),self.order_no.get(),self.wechat_no.get())
        except Exception as exc:self.set_feedback(str(exc),is_error=True);return False
        def render(result):
            self.clear_quote_display()
            if result['status']!='ok':
                self.render_issues([{'级别':'错误','位置':str(i['line_index']),'字段':i['field'],'输入内容':'','提示':i['reason']} for i in result['issues']])
                self.set_feedback('计算失败，整单不可提交。',is_error=True);return
            self._svc_result=result;self._svc_snapshot=snapshot;self._svc_details=details
            for row,line in zip(self.calc_rows,result['lines']):row['res'].set(money_text(int(line['income_cents'])));row['status'].set('OK')
            self.total_val.set('总计：'+money_text(int(result['totals']['income_cents']))+' 元')
            self.summary_income.set(money_text(int(result['totals']['income_cents'])))
            if self.quote_role=='manager':
                for key in ('cost','profit'):getattr(self,'summary_'+key).set(money_text(int(result['totals'][key+'_cents'])))
                self.summary_margin.set(Amounts(int(result['totals']['income_cents']),int(result['totals']['cost_cents'])).display()['margin'] or '—')
                if hasattr(self,'profit_tree'):
                    for line in result['lines']:
                        amounts=Amounts(int(line['income_cents']),int(line['cost_cents'])).display()
                        raw=line['raw'];self.profit_tree.insert('', 'end',values=(raw.get('name') or raw.get('product_id','折扣'),
                            line['normalized'].get('percent',''),amounts['income'],amounts['cost'],amounts['profit'],amounts['margin'] or '—'))
            self.render_issues([]);self.set_feedback('服务计算完成，提交时将再核对当前价格。')
        return self._service_submit('calculate',lambda:client.request('POST','/v1/calculate',{'snapshot':asdict(snapshot)}),render,fresh=True)

    def confirm_current_prices(self):
        if self._svc_result:self.show_price_changes();self._svc_confirmed=True;self.update_quote_status();return True
        self.set_feedback('请按已刷新价格重新计算后确认。');return False

    def show_price_changes(self):
        messagebox.showinfo('价格差异',self._svc_price_diff,parent=self.root)

    def _mutate(self,path,payload,done=None):
        try:client=self._require_client()
        except Exception as exc:self.set_feedback(str(exc),is_error=True);return False
        def saved(value):
            self.set_feedback('已保存请求：'+value.get('request_id',''))
            if done:done(value)
            self.refresh_excel_files()
        return self._service_submit('mutation',lambda:client.mutate(path,payload,self._svc_journal),saved,write=True)

    def export_to_excel(self):
        if not self._svc_result or not self._svc_confirmed:self.set_feedback('请计算并确认当前价格。',is_error=True);return False
        if self._svc_submitted:
            self.set_feedback('此报价已提交：'+self._svc_submitted['order_id']+'。新订单请修改输入并重新计算。');return False
        revision=self.quote_session.state.revision
        def saved(receipt):
            if self.quote_session.state.revision==revision:self._svc_submitted=receipt
        return self._mutate('/v1/orders',{'snapshot':asdict(self._svc_snapshot),'details':asdict(self._svc_details)},saved)

    def save_settings(self):
        if self.quote_role!='manager':return False
        config,issues=QuoteApplicationMixin.get_settings_snapshot(self)
        if issues:self.set_feedback('请修正价格设定。',is_error=True);return False
        items=[{'product_id':name,**p} for name,p in config.items()]
        return self._mutate('/v1/prices',{'prices':{'price_version_id':str(uuid.uuid4()),'items':items},'expected_price_version_id':self._svc_prices['price_version_id'] if self._svc_prices else None},lambda result:self.reload_price_settings_from_json())

    def apply_settings_to_calc(self):return self.save_settings()
    def save_and_apply_settings(self):return self.save_settings()

    def refresh_excel_files(self,*,page=False):
        if not self._svc_client or not hasattr(self,'service_order_tree'):return False
        from urllib.parse import urlencode
        if not page:self._svc_offset=0;self._svc_view=None
        client=self._svc_client;offset=self._svc_offset
        query={'offset':offset,'limit':100,'q':self._svc_search.get() if hasattr(self,'_svc_search') else ''}
        if page and self._svc_view:query['view']=self._svc_view
        def listed(value):
            self._svc_view=value.get('view')
            selected=self.service_order_tree.selection();self.service_order_tree.delete(*self.service_order_tree.get_children())
            self._svc_orders={row['order_id']:row for row in value['orders']}
            for row in value['orders']:
                values=[row['order_id'],row['created_at'],row['details']['order_ref'],money_text(int(row['income_cents'])),row['state'],row['revision']]
                if self.quote_role=='manager':values.extend(money_text(int(row[k])) for k in ('cost_cents','profit_cents'))
                self.service_order_tree.insert('', 'end',iid=row['order_id'],values=values)
            if selected and selected[0] in self._svc_orders:self.service_order_tree.selection_set(selected[0])
            self.set_feedback(f"本页{len(value['orders'])}单，范围内共{value['total']}单；有效收入 {money_text(int(value['totals']['income_cents']))} 元。")
            if self.quote_role=='manager':
                self.set_feedback(f"本页{len(value['orders'])}单，范围内共{value['total']}单；有效收入 {money_text(int(value['totals']['income_cents']))} 元；有效成本 {money_text(int(value['totals']['cost_cents']))} 元；有效利润 {money_text(int(value['totals']['profit_cents']))} 元。")
        return self._service_submit('orders',lambda:client.request('GET','/v1/orders?'+urlencode(query)),listed)

    def request_service_output(self,kind,*,current=False):
        try:
            self._require_client()
            if current:
                if not self._svc_submitted:raise APIError(409,'请先提交当前报价；已保存订单可从服务账本选择。')
                row=self._svc_submitted
            else:row=self._selected_order()
        except Exception as exc:self.set_feedback(str(exc),is_error=True);return False
        return self._mutate('/v1/outputs',{'order_id':row['order_id'],'expected_revision':row['revision'],'kind':kind,'format':'777-output-v1'},
                            lambda value:self.set_feedback('报表任务已保存：'+value['job_id']+'；可在输出任务中查看或补导出。'))

    def show_output_tasks(self):
        try:client=self._require_client()
        except Exception as exc:self.set_feedback(str(exc),is_error=True);return False
        def show(value):
            import tkinter as tk
            window=tk.Toplevel(self.root);window.title('输出任务（补导出不会重复提交订单）')
            tree=ttk.Treeview(window,columns=('kind','state','error'),show='headings',height=12)
            for col,label in [('kind','类型'),('state','状态'),('error','原因')]:tree.heading(col,text=label)
            tree.pack(fill='both',expand=True)
            labels={'excel_quote':'Excel报价','quote_png':'报价图片','excel_admin':'内部明细'}
            states={'queued':'待处理','running':'处理中','failed':'失败，可补导出','done':'已完成'}
            reasons={'OUTPUT_DIRECTORY_NOT_PUBLISHED':'母版尚未发布输出目录','OUTPUT_FILE_CONFLICT':'同名文件内容不同，已保留原件','OUTPUT_IO_FAILED:PermissionError':'文件被占用或目录不可写','OUTPUT_IO_FAILED:FileNotFoundError':'输出目录不可用','OUTPUT_ACCOUNT_CHANGED':'账户权限已变化','OUTPUT_IMAGE_TOO_TALL':'内容过长，请使用Excel'}
            for row in value['jobs']:tree.insert('', 'end',iid=row['job_id'],values=(labels.get(row['kind'],row['kind']),states.get(row['state'],row['state']),reasons.get(row['error'],'输出失败，订单已保存' if row['error'] else '')))
            def selected():
                values=tree.selection()
                if not values:raise APIError(422,'请选择输出任务')
                return values[0]
            def retry():
                try:key=selected()
                except Exception as exc:self.set_feedback(str(exc),is_error=True);return
                self._mutate('/v1/outputs/'+key+'/retry',{},lambda _:window.destroy())
            def download():
                try:key=selected()
                except Exception as exc:self.set_feedback(str(exc),is_error=True);return
                def ready(value):
                    extension='.png' if value['media_type']=='image/png' else '.xlsx'
                    path=filedialog.asksaveasfilename(parent=window,initialfile=value['filename'],defaultextension=extension)
                    if not path:return
                    def save():
                        return save_output_content(value,Path(path))
                    self._service_submit('output_download',save,lambda _:self.set_feedback('输出副本已保存。'),write=True)
                self._service_submit('output_content',lambda:client.request('GET','/v1/outputs/'+key+'/content'),ready)
            ttk.Button(window,text='补导出原任务',command=retry).pack(side='left')
            ttk.Button(window,text='另存输出副本',command=download).pack(side='left')
            ttk.Button(window,text='刷新',command=lambda:(window.destroy(),self.show_output_tasks())).pack(side='left')
        return self._service_submit('output_tasks',lambda:client.request('GET','/v1/outputs'),show)

    def aggregate_all_excels(self,silent=False):return self.refresh_excel_files()
    def _selected_order(self):
        selected=self.service_order_tree.selection()
        if not selected:raise APIError(422,'请选择服务订单')
        return self._svc_orders[selected[0]]

    def load_current_excel_sheet(self):
        try:client=self._require_client();row=self._selected_order()
        except Exception as exc:self.set_feedback(str(exc),is_error=True);return False
        def displayed(order):
            self._svc_orders[order['order_id']]=order
            self.service_detail_var.set('订单：'+order['details']['order_ref']+'；客户：'+order['details']['customer']+'；版本：'+str(order['revision']))
            output=[]
            for line in order['lines']:
                raw=line['raw'];normal=line['normalized']
                label=raw.get('name') or raw.get('product_id','折扣')
                output.append(f"{line['sequence']}. {label}；数量 {normal.get('q','—')}；金额 {money_text(int(line['income_cents']))} 元"+
                    (f"；成本 {money_text(int(line['cost_cents']))}；利润 {money_text(int(line['profit_cents']))}" if self.quote_role=='manager' else ''))
            output.append('备注历史：');output.extend(note['created_at']+' '+note['body'] for note in order['notes'])
            self.service_detail_text.configure(state='normal');self.service_detail_text.delete('1.0','end');self.service_detail_text.insert('1.0','\n'.join(output));self.service_detail_text.configure(state='disabled')
        return self._service_submit('detail',lambda:client.request('GET','/v1/orders/'+row['order_id']),displayed)

    def save_current_excel_remark(self):
        try:row=self._selected_order()
        except Exception as exc:self.set_feedback(str(exc),is_error=True);return False
        value=simpledialog.askstring('追加备注','备注只追加到已提交订单：',parent=self.root)
        if value:return self._mutate('/v1/notes',{'order_id':row['order_id'],'body':value,'expected_revision':row['revision']})

    def _service_state(self,state):
        if self.quote_role!='manager':return False
        try:row=self._selected_order()
        except Exception as exc:self.set_feedback(str(exc),is_error=True);return False
        reason=simpledialog.askstring('作废／恢复','请输入操作原因：',parent=self.root)
        if reason:return self._mutate('/v1/state',{'order_id':row['order_id'],'state':state,'reason':reason,'expected_revision':row['revision']})
    def delete_current_excel_row(self):return self._service_state('void')
    def restore_current_excel_order(self):return self._service_state('active')

    def check_last_write(self):return self._check_service_pending(False)
    def retry_service_request(self):return self._check_service_pending(True)
    def _check_service_pending(self,retry):
        try:client=self._require_client()
        except Exception as exc:self.set_feedback(str(exc),is_error=True);return False
        def checked(value):
            self.set_feedback('原请求已确认保存。' if value['result'] else '服务尚无原请求回执；可按原请求重试。' if value['pending'] else '没有待核查请求。')
            self.refresh_excel_files()
        return self._service_submit('receipt',lambda:client.check_pending(self._svc_journal,retry=retry),checked,write=True)

    def apply_export_dir(self):
        if self.quote_role!='manager' or not self._svc_preferences:return False
        client=self._require_client();payload={'revision':self._svc_preferences['revision'],'export_dir':self.export_dir_var.get(),'image_dir':self.screenshot_dir_var.get()}
        return self._service_submit('directories',lambda:client.request('POST','/v1/settings',payload),lambda result:self.reload_price_settings_from_json(),write=True)

    def create_service_account(self):
        if self.quote_role!='manager':return False
        client=self._require_client();user=simpledialog.askstring('创建账号','用户名：',parent=self.root)
        if not user:return False
        role=simpledialog.askstring('创建账号','角色：admin 或 sales',parent=self.root,initialvalue='sales')
        secret=simpledialog.askstring('创建账号','密码（12～128字）：',show='●',parent=self.root)
        if secret:return self._service_submit('accounts',lambda:client.request('POST','/v1/accounts',{'username':user,'password':secret,'role':role}),lambda result:self.set_feedback('账号已创建：'+result['username']),write=True)

    def show_service_backup(self):
        if self.quote_role!='manager':return False
        client=self._require_client()
        return self._service_submit('backup',lambda:client.request('GET','/v1/backup'),lambda result:messagebox.showinfo('主机备份状态',json.dumps(result,ensure_ascii=False,indent=2),parent=self.root))

    def run_service_backup(self):
        if self.quote_role!='manager':return False
        client=self._require_client()
        return self._service_submit('backup_run',lambda:client.request('POST','/v1/backup',{'kind':'maintenance'}),lambda result:self.set_feedback('维护备份及独立恢复核验已完成。'),write=True)

    def edit_service_backup_plan(self):
        if self.quote_role!='manager':return False
        client=self._require_client()
        def edit(status):
            plan=status['plan'];changed=dict(plan)
            labels={'interval_minutes':'有变更滚动备份间隔（分钟）','daily_hour':'每日备份小时（0～23）','rolling':'滚动保留数量','daily':'每日保留数量','offset_minutes':'时区相对UTC分钟（中国为480）'}
            for field,label in labels.items():
                value=simpledialog.askinteger('主机备份计划',label,parent=self.root,initialvalue=plan[field])
                if value is None:return
                changed[field]=value
            self._service_submit('backup_plan',lambda:client.request('POST','/v1/backup-plan',changed),lambda result:self.set_feedback('主机备份计划已保存。'),write=True)
        return self._service_submit('backup_plan_read',lambda:client.request('GET','/v1/backup'),edit)

    def manage_service_accounts(self):
        if self.quote_role!='manager':return False
        client=self._require_client()
        def show(value):
            from tkinter import Toplevel
            window=Toplevel(self.root);window.title('服务账号管理')
            tree=ttk.Treeview(window,columns=('username','role','enabled'),show='headings',height=10)
            for column,label in [('username','用户名'),('role','角色'),('enabled','启用')]:tree.heading(column,text=label)
            tree.pack(fill='both',expand=True);accounts={r['id']:r for r in value['accounts']}
            for row in accounts.values():tree.insert('', 'end',iid=row['id'],values=(row['username'],row['role'],bool(row['enabled'])))
            def update(reset=False):
                selected=tree.selection()
                if not selected:return
                row=accounts[selected[0]]
                if reset:
                    secret=simpledialog.askstring('重设密码','新密码（12～128字）：',show='●',parent=window)
                    if secret is None:return
                    data={'password':secret}
                else:data={'enabled':not bool(row['enabled'])}
                self._service_submit('account_update',lambda:client.request('POST','/v1/accounts/'+row['id'],data),lambda result:(window.destroy(),self.set_feedback('账号已更新；原会话已失效。')),write=True)
            ttk.Button(window,text='启用／禁用',command=update).pack(side='left')
            ttk.Button(window,text='重设密码',command=lambda:update(True)).pack(side='left')
        return self._service_submit('account_list',lambda:client.request('GET','/v1/accounts'),show)

    def cancel_background_reads(self):self._svc_jobs.cancel_reads();self.set_feedback('已取消读取结果更新。')
    def on_close(self):
        self._svc_closing=True;self._svc_jobs.cancel_reads()
        self.root.after_cancel(self._svc_settings_poll)
        if not self._svc_jobs.writing:
            self.root.after_cancel(self._svc_poll_job);self._svc_jobs.close();self.root.destroy()


def application_type(role,settings_file):
    root=Path(__file__).resolve().parents[1]
    manifest=json.loads((root/'docs/baseline/manifest.json').read_text(encoding='utf-8'))
    path=root/next(item['path'] for item in manifest['files'] if item['role']==role)
    namespace={'__name__':'quote_service_'+role,'__file__':str(path)}
    exec(compile(path.read_bytes(),str(path),'exec'),namespace)
    parent=namespace['PriceCalculator']
    class ServiceCalculator(ServiceApplicationMixin,parent):
        service_settings_file=str(settings_file)
    return ServiceCalculator


def save_output_content(value,path):
    """Only a selected new local copy; no workbook mutation or order submission."""
    import base64
    from quote_service.output_render import FORMAT,MAX_BYTES
    if value.get('format')!=FORMAT:raise APIError(409,'OUTPUT_VERSION_CONFLICT')
    try:raw=base64.b64decode(value['data_base64'],validate=True)
    except (ValueError,TypeError):raise APIError(422,'OUTPUT_CONTENT_INVALID') from None
    if len(raw)>MAX_BYTES or len(raw)!=value['size'] or hashlib.sha256(raw).hexdigest()!=value['sha256']:raise APIError(422,'OUTPUT_CONTENT_INVALID')
    with open(path,'xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    return {'saved':True,'sha256':value['sha256']}
