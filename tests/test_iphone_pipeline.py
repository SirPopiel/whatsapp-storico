import pathlib
import sys
import tempfile
import unittest
import plistlib
import sqlite3
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import iphone_pipeline as p


def m(key, text='a'):
    return {'key_id':key,'timestamp':1451602800,'from_me':True,'message_type':0,'data':text,'meta':False}


class BackupTests(unittest.TestCase):
    def test_incomplete_snapshot_never_ready(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td)
            for name in ('Info.plist','Manifest.plist'):
                (root/name).write_bytes(plistlib.dumps({}))
            (root/'Manifest.db').write_bytes(b'placeholder')
            (root/'Status.plist').write_bytes(plistlib.dumps({'SnapshotState':'in_progress'}))
            self.assertFalse(p.readiness(root)[0])
            (root/'Status.plist').write_bytes(plistlib.dumps({'SnapshotState':'finished'}))
            self.assertTrue(p.readiness(root)[0])

    def test_manifest_missing_payload_blocks_export(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td)
            for name,value in [('Info.plist',{'Device Name':'Test'}),('Manifest.plist',{'IsEncrypted':False}),('Status.plist',{'SnapshotState':'finished'})]:
                (root/name).write_bytes(plistlib.dumps(value))
            with sqlite3.connect(root/'Manifest.db') as c:
                c.execute('CREATE TABLE Files (fileID TEXT, relativePath TEXT, domain TEXT, flags INTEGER)')
                c.execute("INSERT INTO Files VALUES ('abcd','ChatStorage.sqlite','AppDomainGroup-group.net.whatsapp.WhatsApp.shared',1)")
            with self.assertRaisesRegex(RuntimeError,'file dichiarati'):
                p.validate(root)

    def test_overlap_and_stable_only_integration(self):
        phone={'a@s.whatsapp.net':{'name':'A','messages':{'1':m('same')}}}
        mac={'a@s.whatsapp.net':{'name':'A','messages':{'1':m('same'),'2':m('new'),'3':m(None)}}}
        combined,counts,unresolved,conflicts=p.integrate(phone,mac,{})
        self.assertEqual(len(combined['a@s.whatsapp.net']['messages']),2)
        self.assertEqual(counts['overlapping_stable_records'],1)
        self.assertEqual(counts['mac_unique_stable_records_integrated'],1)
        self.assertEqual(len(unresolved),1)
        self.assertFalse(conflicts)
        self.assertEqual(len(phone['a@s.whatsapp.net']['messages']),1)

    def test_verified_aliases_overlap_and_conflicts_keep_iphone(self):
        phone={'a@s.whatsapp.net':{'name':'A','messages':{'1':m('same','phone')}}}
        mac={'b@lid':{'name':'A','messages':{'1':m('same','mac')}}}
        combined,counts,unresolved,conflicts=p.integrate(phone,mac,{'b@lid':'a@s.whatsapp.net'})
        self.assertEqual(len(combined),1)
        self.assertEqual(combined['a@s.whatsapp.net']['messages']['1']['data'],'phone')
        self.assertEqual(counts['conflicting_stable_records_iphone_kept'],1)
        self.assertEqual(len(conflicts),1)


if __name__=='__main__': unittest.main()
