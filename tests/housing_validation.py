"""Meaningful exact solid fixtures for imported entire-groove add/remove guards."""
import sys,unittest,tempfile,math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from housing import boolean,make_plan,inventory,load_step,mass,digest
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
from OCP.STEPControl import STEPControl_Writer,STEPControl_AsIs

def write(shape,path):
 w=STEPControl_Writer();w.Transfer(shape,STEPControl_AsIs);w.Write(str(path))

class Tests(unittest.TestCase):
 def setUp(self):
  # All intermediates respect the project output location.
  self.tmp=tempfile.TemporaryDirectory(dir=tempfile.gettempdir(),prefix='housing-test-');self.root=Path(self.tmp.name)
 def tearDown(self):self.tmp.cleanup()
 def fixture(self,outer=30):
  shape=boolean(BRepPrimAPI_MakeCylinder(outer,12).Shape(),BRepPrimAPI_MakeCylinder(20,12).Shape(),'cut')
  path=self.root/'base.step';write(shape,path);return path
 def top_id(self,path):
  return max(inventory(path,'Z')['annular_planar_candidates'],key=lambda r:r['coordinate_mm'])['face_id']
 def test_add_whole_ring_remove_original_imported_ring(self):
  path=self.fixture();original=digest(path)
  added=make_plan(path,self.root/'add','add_groove',self.top_id(path),axis='Z')
  expected=math.pi*(25.5**2-22.5**2)*4
  self.assertAlmostEqual(-added['volume_delta_mm3'],expected,places=5)
  inv=inventory(added['candidate_step'],'Z')
  bottom=next(p for p in inv['annular_planar_candidates'] if abs(p['coordinate_mm']-8)<1e-6)
  restored=make_plan(added['candidate_step'],self.root/'remove','remove_existing',bottom['face_id'],axis='Z',rim_coordinate=12)
  self.assertAlmostEqual(restored['volume_after_mm3'],mass(load_step(path),True),places=5)
  self.assertAlmostEqual(mass(boolean(load_step(path),load_step(restored['candidate_step']),'cut'),True),0,places=5)
  self.assertAlmostEqual(mass(boolean(load_step(restored['candidate_step']),load_step(path),'cut'),True),0,places=5)
  self.assertEqual(digest(path),original)
 def test_reject_insufficient_rim(self):
  path=self.fixture(22)
  with self.assertRaisesRegex(ValueError,'超出'):make_plan(path,self.root/'no','add_groove',self.top_id(path),axis='Z')
 def test_reject_depth_breakthrough(self):
  path=self.fixture()
  with self.assertRaisesRegex(ValueError,'穿透'):make_plan(path,self.root/'no','add_groove',self.top_id(path),axis='Z',depth=14)
 def test_reject_fake_face_and_nonfinite_dimensions(self):
  path=self.fixture()
  for face,width in [('face:999',3),('face:0',float('nan'))]:
   with self.subTest(face=face),self.assertRaises(ValueError):make_plan(path,self.root/'no','add_groove',face,axis='Z',width=width)

if __name__=='__main__':unittest.main()
