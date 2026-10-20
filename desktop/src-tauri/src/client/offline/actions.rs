use super::*;
impl Desktop {
    pub(in crate::client) fn local_action(&mut self, action: &Action) -> Result<Option<Value>> {
        use Action::*;
        let result=match action{
            LocalReceipt{operation_id}=>self.local.saved_receipt(identifier(operation_id)?)?,
            Settings{}=>match self.local.meta("settings")?{Some(v)=>v,None=>return Ok(None)},
            Prices{}=>{if self.local.meta("prices_changed")?==Some(json!(true)){return Ok(None)}self.local.context()?["catalog"].clone()},
            Calculate{snapshot,draft_revision}=>{
                let body=json!({"snapshot":snapshot,"sources":null,"order_id":null,"expected_revision":null});
                let result=self.local.calculate(&body)?;
                self.calculation=Some(Calculation{snapshot:snapshot.clone(),revision:draft_revision.clone(),result:result.clone()});
                json!({"draft_revision":draft_revision,"result":result})
            }
            OrderPreview{snapshot,sources,order_id,expected_revision,draft_revision}=>{
                let body=json!({"snapshot":snapshot,"sources":sources,"order_id":order_id,"expected_revision":expected_revision});
                let result=self.local.calculate(&body)?;
                self.calculation=Some(Calculation{snapshot:body,revision:draft_revision.clone(),result:result.clone()});
                json!({"draft_revision":draft_revision,"result":result})
            }
            SaveOrder{snapshot,sources,order_id,expected_revision,draft_revision,details,customer,operation_id}=>{
                let mut body=json!({"snapshot":snapshot,"sources":sources,"order_id":order_id,"expected_revision":expected_revision});
                body["details"]=details.clone();body["customer"]=customer.clone();body["operation_id"]=json!(operation_id);
                if let Some(v)=self.local.replay("save",&body)?{return Ok(Some(v))}
                let calculation=json!({"snapshot":snapshot,"sources":sources,"order_id":order_id,"expected_revision":expected_revision});
                self.local_calculation(&calculation,draft_revision)?;
                let result=self.local.save("save",&body)?;self.calculation=None;result
            }
            Submit{snapshot,details,draft_revision,operation_id}=>{
                let body=json!({"snapshot":snapshot,"sources":null,"order_id":null,"expected_revision":null,"details":details,"customer":{},"operation_id":operation_id});
                if let Some(v)=self.local.replay("save",&body)?{return Ok(Some(v))}
                self.local_calculation(snapshot,draft_revision)?;
                let result=self.local.save("save",&body)?;self.calculation=None;result
            }
            Order{order_id}=>self.local.order(order_id)?,
            Orders{q,state,offset,view}=>self.local.listing(q,state,*offset,view)?,
            CustomerOrders{query,offset,group_id,order_offset}=>self.local.customers(query,*offset,group_id.as_deref(),order_offset.unwrap_or(0))?,
            OrderChanges{order_id,revision}=>match self.local.changes(order_id,revision){Ok(v)=>v,Err(e)if e.status==404=>return Ok(None),Err(e)=>return Err(e)},
            Note{order_id,expected_revision,body}=>self.local.save("note",&json!({"order_id":order_id,"expected_revision":expected_revision,"body":body}))?,
            SetState{order_id,expected_revision,state,reason}=>self.local.save("state",&json!({"order_id":order_id,"expected_revision":expected_revision,"state":state,"reason":reason}))?,
            _=>return Ok(None)
        };
        Ok(Some(result))
    }
    fn local_calculation(&self, body: &Value, revision: &str) -> Result<()> {
        let c = self
            .calculation
            .as_ref()
            .ok_or_else(|| DesktopError::new(409, "CALCULATION_REQUIRED"))?;
        if c.snapshot != *body || c.revision != revision || c.result["status"] != "ok" {
            return Err(DesktopError::new(409, "CALCULATION_STALE"));
        }
        Ok(())
    }
}
