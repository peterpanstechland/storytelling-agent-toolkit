import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('story',ROOT/'skills/storytelling/scripts/story.py');story=importlib.util.module_from_spec(spec);spec.loader.exec_module(story)
class StoryTests(unittest.TestCase):
 def brief(self):return json.loads((ROOT/'skills/storytelling/templates/demo-brief.json').read_text())
 def test_all_requested_channels_create_local_packages(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);p=root/'brief.json';p.write_text(json.dumps(self.brief()));out=root/'pack'
   rows=story.pack(p,out,None);self.assertEqual(len(rows),10)
   for row in rows:
    data=json.loads((out/row['directory']/'metadata.json').read_text());self.assertEqual(data['publication_state'],'local_only')
   x=json.loads((out/'x/thread.json').read_text());self.assertEqual(len(x['posts']),2)
   self.assertTrue((out/'youtube/description.txt').is_file())
 def test_fact_needs_evidence(self):
  data=self.brief();data['claims']=[{'id':'a','kind':'fact','text':'A number'}]
  self.assertTrue(any('no evidence' in e for e in story.errors_for(data,ROOT)))
 def test_metric_needs_meaning_and_scope(self):
  data=self.brief();data['claims']=[{'id':'a','kind':'fact','source_ids':['demo'],'metric':True}]
  self.assertTrue(any('meaning and scope' in e for e in story.errors_for(data,ROOT)))
 def test_other_presenter_cannot_represent_author(self):
  data=self.brief();data['assets']=[{'id':'shot','path':'shot.mp4','usage':'user-provided','people':[{'represents_author':True,'identity_confirmed':False}]}]
  self.assertTrue(any('identity' in e for e in story.errors_for(data,ROOT)))
 def test_only_selected_assets_copied(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'chosen.txt').write_text('selected');(root/'private.txt').write_text('unselected')
   data=self.brief();data['platforms']=['bilibili'];data['assets']=[{'id':'chosen','path':'chosen.txt','usage':'test'},{'id':'private','path':'private.txt','usage':'test'}];data['variants']={'bilibili':{'asset_ids':['chosen']}}
   p=root/'brief.json';p.write_text(json.dumps(data));story.pack(p,root/'pack',None,True)
   copied=list((root/'pack/bilibili/media').iterdir());self.assertEqual(len(copied),1);self.assertEqual(copied[0].read_text(),'selected')
 def test_existing_release_not_overwritten(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);p=root/'brief.json';p.write_text(json.dumps(self.brief()));out=root/'pack';out.mkdir();(out/'keep.txt').write_text('keep')
   with self.assertRaises(ValueError):story.pack(p,out,None)
   self.assertEqual((out/'keep.txt').read_text(),'keep')
 def test_selected_order_controls_carousel_and_markdown_paths(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)
   for name in ['end','open']: (root/f'{name}.png').write_bytes(name.encode())
   data=self.brief();data['platforms']=['xiaohongshu'];data['assets']=[{'id':name,'path':f'{name}.png','usage':'test'} for name in ['end','open']]
   data['variants']={'xiaohongshu':{'asset_ids':['open','end'],'body_markdown':'![Opening](open.png)\n\n![Ending](end.png)'}}
   p=root/'brief.json';p.write_text(json.dumps(data));story.pack(p,root/'pack',None,True)
   folder=root/'pack/xiaohongshu';meta=json.loads((folder/'metadata.json').read_text())
   self.assertEqual([x['id'] for x in meta['attachments']],['open','end'])
   self.assertEqual((folder/'media/01.png').read_bytes(),b'open')
   md=(folder/'article.md').read_text();self.assertIn('![Opening](media/01.png)',md);self.assertIn('![Ending](media/02.png)',md)
   self.assertNotIn('(open.png)',md)
 def test_raw_html_cannot_execute(self):
  page=story.article_html('<script>alert(1)</script>','A',[])
  self.assertNotIn('<script>',page);self.assertIn('&lt;script&gt;',page)
 def test_missing_or_unmapped_image_not_silently_dropped(self):
  with self.assertRaises(ValueError):story.article_html('![Caption](secret.png)','A',[])
 def test_schema_error_not_traceback(self):
  self.assertTrue(story.errors_for([],ROOT));data=self.brief();data['sources']={};self.assertTrue(story.errors_for(data,ROOT))
if __name__=='__main__':unittest.main()
