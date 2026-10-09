import importlib.util
import pathlib
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('update', pathlib.Path(__file__).resolve().parents[1] / 'update.py')
u = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(u)


def message(date, key, sent=False, kind=0, text='hello', meta=False):
    return {'timestamp': u.dt.datetime.fromisoformat(date).timestamp(), 'key_id': key, 'from_me': sent, 'message_type': kind, 'data': text, 'meta': meta}


class ReportTests(unittest.TestCase):
    def test_year_cutoff_groups_system_vcard_and_lid(self):
        data = {
            'a@s.whatsapp.net': {'name': 'Alice', 'messages': {
                '1': message('2013-12-31T23:00:00+01:00', 'a1', True),
                '2': message('2014-12-31T23:59:59+01:00', 'a2'),
                '3': message('2015-01-01T00:00:00+01:00', 'a3'),
                '4': message('2014-03-01T12:00:00+01:00', 'sys', kind=6),
                '5': message('2014-03-01T12:01:00+01:00', 'card', kind=4, meta=True)}},
            'b@lid': {'name': 'Bob', 'messages': {'1': message('2015-06-01T12:00:00+02:00', 'b1')}},
            'group@g.us': {'name': 'Group', 'messages': {'1': message('2014-01-01T12:00:00+01:00', 'g1')}}}
        with tempfile.TemporaryDirectory() as td:
            merged, added = u.merge(data, pathlib.Path(td) / 'archive.sqlite', {})
            r = u.make_report(merged, 2014, 2015)
        self.assertEqual(r['years']['2014']['stats']['total'], 3)
        self.assertEqual(r['years']['2014']['top30'][0]['annual'], 2)
        self.assertEqual(r['years']['2014']['top30'][0]['sent'], 1)
        self.assertEqual(r['years']['2015']['stats']['total'], 5)
        self.assertEqual(r['quality']['excluded_system_records'], 1)
        self.assertEqual(r['quality']['excluded_chats'], 1)
        self.assertEqual(r['quality']['unmapped_lid_chats'], 1)
        self.assertTrue(r['years']['2015']['top30'][1]['new_chat'])

    def test_idempotent_updates_keep_older_deleted_messages_and_multiplicity(self):
        x = message('2014-01-01T12:00:00+01:00', None)
        first = {'a@s.whatsapp.net': {'name': 'A', 'messages': {'1': x, '2': dict(x), '3': message('2014-02-01T12:00:00+01:00', 'unique')}}}
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td) / 'archive.sqlite'
            m, added = u.merge(first, path, {})
            self.assertEqual(added, 3)
            m, added = u.merge(first, path, {})
            self.assertEqual(added, 0)
            second = {'a@s.whatsapp.net': {'name': 'A renamed', 'messages': {'3': message('2014-02-01T12:00:00+01:00', 'unique'), '4': message('2015-03-01T12:00:00+01:00', 'new')}}}
            m, added = u.merge(second, path, {})
            self.assertEqual(added, 1)
            self.assertEqual(len(m['a@s.whatsapp.net']['messages']), 4)
            self.assertEqual(m['a@s.whatsapp.net']['name'], 'A renamed')

    def test_annual_rank_differs_from_cumulative_rank(self):
        data={'a@s.whatsapp.net':{'name':'A','individual':True,'messages':{str(i):message('2014-01-01T12:00:00+01:00',f'a{i}') for i in range(10)}},
              'b@s.whatsapp.net':{'name':'B','individual':True,'messages':{'1':message('2015-01-01T12:00:00+01:00','b')}}}
        r=u.make_report(data,2014,2015)
        self.assertEqual(r['years']['2015']['top30'][0]['name'],'A')
        self.assertEqual(r['years']['2015']['annual_top30'][0]['name'],'B')
        self.assertEqual(r['years']['2015']['annual_top30'][0]['annual_rank'],1)
        series={x['name']:x['annual'] for x in r['chat_series']}
        self.assertEqual(r['series_years'],[2014,2015])
        self.assertEqual(series['A'],[10,0])
        self.assertEqual(series['B'],[0,1])

    def test_top50_monthly_series_and_annual_sort_data(self):
        data = {}
        for i in range(60):
            jid=f'{i}@s.whatsapp.net'
            data[jid]={'name':f'Person {i:02d}','individual':True,'messages':{str(n):message('2014-01-15T12:00:00+01:00',f'{i}-{n}') for n in range(i+1)}}
        report=u.make_report(data,2014,2014)
        year=report['years']['2014']
        self.assertEqual(len(year['top50']),50)
        self.assertEqual(len(year['annual_top50']),50)
        self.assertEqual(year['top50'][0]['name'],'Person 59')
        self.assertEqual(year['stats']['top50_share_pct'],round(sum(i+1 for i in range(10,60))/sum(i+1 for i in range(60))*100,1))
        self.assertEqual(report['monthly_messages'],[{'month':'2014-01','sent':0,'received':1830,'total':1830}])

    def test_name_case_normalization_and_duplicate_name_merge(self):
        data={
          'a@s.whatsapp.net':{'name':"'claudia speranza'",'individual':True,'messages':{'a':message('2014-01-01T12:00:00+01:00','a')}},
          'b@s.whatsapp.net':{'name':'Claudia Speranza','individual':True,'messages':{'b':message('2014-02-01T12:00:00+01:00','b')}},
          'c@s.whatsapp.net':{'name':'PayPal','individual':True,'messages':{'c':message('2014-03-01T12:00:00+01:00','c')}},
          'd@s.whatsapp.net':{'name':'PayPal','individual':True,'messages':{'d':message('2014-04-01T12:00:00+01:00','d')}}}
        report=u.make_report(data,2014,2014)
        self.assertEqual(u.normalize_contact_name("'claudia speranza'"),'Claudia Speranza')
        self.assertEqual(report['quality']['merged_duplicate_name_groups'],1)
        self.assertEqual(report['quality']['merged_duplicate_name_chats'],1)
        self.assertEqual(report['years']['2014']['stats']['contacts'],3)
        merged=[r for r in report['years']['2014']['ranking'] if r['name']=='Claudia Speranza']
        self.assertEqual(len(merged),1)
        self.assertEqual(merged[0]['total'],2)
        self.assertEqual(sum(r['total'] for r in report['years']['2014']['ranking'] if r['name']=='PayPal'),2)


    def test_private_name_overrides_take_precedence(self):
        data={'123@s.whatsapp.net':{'name':'Original Name','individual':True,'messages':{'1':message('2014-01-01T12:00:00+01:00','stable')}}}
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td)
            (root/'name_overrides.json').write_text('{"123@s.whatsapp.net":"Shared Name"}',encoding='utf-8')
            (root/'name_overrides.local.json').write_text('{"123@s.whatsapp.net":"Private Name"}',encoding='utf-8')
            with mock.patch.object(u,'ROOT',root):
                report=u.make_report(data,2014,2014)
        self.assertEqual(report['years']['2014']['ranking'][0]['name'],'Private Name')

    def test_movers_use_full_ranking_and_aliases_deduplicate(self):
        a = message('2014-01-01T12:00:00+01:00', 'a')
        data = {'a@s.whatsapp.net': {'name': 'A', 'individual': True, 'messages': {'a': a}},
                'a@lid': {'name': 'A', 'individual': True, 'messages': {'a': dict(a)}},
                'b@s.whatsapp.net': {'name': 'B', 'individual': True, 'messages': {'b1': message('2014-01-01T12:00:00+01:00', 'b1'), 'b2': message('2015-01-01T12:00:00+01:00', 'b2')}}}
        r = u.make_report(data, 2014, 2015, {'a@lid': 'a@s.whatsapp.net'})
        self.assertEqual(r['years']['2014']['stats']['total'], 2)
        self.assertEqual(r['years']['2015']['top30'][0]['name'], 'B')
        self.assertEqual(r['years']['2015']['top30'][0]['rank_change'], 1)
        self.assertEqual(r['quality']['alias_duplicate_records'], 1)


if __name__ == '__main__':
    unittest.main()
