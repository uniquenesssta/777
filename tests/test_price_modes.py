import json
import unittest
from quote_core import PriceItem, PriceSnapshot, QuoteSnapshot, NormalLine, calculate_quote, parse_price_config
from quote_core.models import price_wire
from quote_core.numbers import decimal_text
from quote_core.pricing import unit_sale

class PriceModesTests(unittest.TestCase):
    def test_manual_auto_and_legacy_keep_distinct_final_price(self):
        q=QuoteSnapshot('v1',(NormalLine('P','1'),))
        for mode,expected in [(None,4000),('manual',2000),('cost_plus',2300)]:
            p=PriceItem('P','20','11.5','2',True,mode)
            result=calculate_quote(q,PriceSnapshot('v1',(p,)))
            self.assertEqual(result.totals.income_cents,expected)
            self.assertEqual('pricing_mode' in price_wire(p),mode is not None)
    def test_auto_recomputes_forged_sale_and_settles_only_after_quantity(self):
        parsed=parse_price_config(json.dumps({'items':[dict(name='P',sale='forged',cost='0.335',k='3',single=True,pricing_mode='cost_plus')]}),price_version_id='v1')
        self.assertEqual(parsed.status,'ok')
        p=parsed.config.prices
        self.assertEqual(p.items[0].sale,'1.005')
        self.assertEqual(decimal_text(unit_sale(p.items[0])),'1.005')
        self.assertEqual(calculate_quote(QuoteSnapshot('v1',(NormalLine('P','3'),)),p).totals.income_cents,302)
    def test_legacy_controller_does_not_double_markup_or_erase_new_price_policy(self):
        from quote_app.service_client import ServiceApplicationMixin
        controller=ServiceApplicationMixin()
        controller.quote_role='manager'
        controller._svc_prices={'items':[dict(product_id='P',sale='23',cost='11.5',k='2',single=True,pricing_mode='cost_plus')]}
        mapping=controller._price_mapping()
        self.assertEqual(mapping['P']['k'],'1')
        p=PriceItem('P',**mapping['P'])
        self.assertEqual(calculate_quote(QuoteSnapshot('v1',(NormalLine('P','1'),)),PriceSnapshot('v1',(p,))).totals.income_cents,2300)
        messages=[]
        controller.set_feedback=lambda text,**kwargs:messages.append(text)
        self.assertFalse(controller.save_settings())
        self.assertIn('桌面端',messages[0])

    def test_new_metadata_is_strict_and_zero_blank_k_and_large_products_work(self):
        for cost,k,expected in [('0','2','0'),('11.5','0','0'),('11.5','','11.5'),('1000000000','1000000000','1000000000000000000')]:
            p=parse_price_config(json.dumps({'items':[dict(name='P',sale='',cost=cost,k=k,single=True,pricing_mode='cost_plus')]}),price_version_id='v1')
            self.assertEqual(p.config.prices.items[0].sale,expected)
        for mode in ['unknown',True,None]:
            p=parse_price_config(json.dumps({'items':[dict(name='P',sale='20',cost='11.5',k='2',single=True,pricing_mode=mode)]}),price_version_id='v1')
            self.assertEqual(p.status,'VALIDATION')

if __name__=='__main__':unittest.main()
