"""Calendar interpretation must not silently guess conflicting collection types."""
import importlib.util,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('bin_schedule',Path(__file__).parents[1]/'extras/frame_bin_reminder/schedule.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
class Tests(unittest.TestCase):
 def classify(self,events):return mod.collection_from_events(events,['blue','recycling'],['black','general waste'])
 def test_blue(self):self.assertEqual(self.classify([{'summary':'Recycling collection'}]),'blue')
 def test_black(self):self.assertEqual(self.classify([{'summary':'BLACK bin'}]),'black')
 def test_confirmed_empty_calendar_day(self):self.assertEqual(self.classify([]),'none')
 def test_unavailable_response_is_not_no_collection(self):
  for response in (None,{},'unavailable'):
   with self.assertRaises(ValueError):self.classify(response)
 def test_ambiguous_and_unrelated_events_fail(self):
  for events in ([{'summary':'Blue and black'}],[{'summary':'Dentist'}],[{'summary':'blue'},{'summary':'black'}]):
   with self.assertRaises(ValueError):self.classify(events)
 def test_keywords_case_insensitive_and_empty_keyword_ignored(self):self.assertEqual(mod.collection_from_events([{'summary':'RECYCLING'}],['','recycling'],['black']),'blue')
