"""Analytic control surfaces and actual multimodal wire format, without network."""
import sys,unittest,json,tempfile,threading
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from section_analysis import sample_curvature,section_bending
from responses_api import input_items
from controller import Controller
from OCP.TColgp import TColgp_Array2OfPnt
from OCP.Geom import Geom_BezierSurface
from OCP.gp import gp_Pnt,gp_Ax1,gp_Dir,gp_Trsf
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace,BRepBuilderAPI_Transform


def control(a,b):
    p=TColgp_Array2OfPnt(1,3,1,3)
    for i,x in enumerate([-50,0,50],1):
        for j,y in enumerate([-50,0,50],1):
            p.SetValue(i,j,gp_Pnt(x,y,(a*[2500,-2500,2500][i-1]+b*[2500,-2500,2500][j-1])/1000))
    return BRepBuilderAPI_MakeFace(Geom_BezierSurface(p),1e-7).Face()


class Tests(unittest.TestCase):
    def test_analytic_controls_and_normal_reversal(self):
        for a,b,label in [(-1,-1,'convex_toward_reference'),(1,1,'concave_toward_reference'),(1,-1,'saddle'),(0,0,'flat')]:
            shape=control(a,b);report=sample_curvature(shape,[0,0,1],5)
            self.assertEqual(report['count_by_class'],{label:25});self.assertEqual(report['errors'],[])
            reverse=sample_curvature(shape,[0,0,-1],5)
            expected={'convex_toward_reference':'concave_toward_reference','concave_toward_reference':'convex_toward_reference'}.get(label,label)
            self.assertEqual(reverse['count_by_class'],{expected:25})

    def test_rotated_fender_direction(self):
        import math
        transform=gp_Trsf();transform.SetRotation(gp_Ax1(gp_Pnt(0,0,0),gp_Dir(1,0,0)),-math.pi/2)
        shape=BRepBuilderAPI_Transform(control(-1,-1),transform,True).Shape()
        self.assertEqual(sample_curvature(shape,[0,1,0],5)['count_by_class'],{'convex_toward_reference':25})
        self.assertEqual(sample_curvature(shape,[0,0,1],5)['count_by_class'],{'normal_transverse':25})

    def test_section_bending_sign_independent_of_traversal(self):
        import numpy as np
        points=[[float(x),0.,-float(x*x)/1000] for x in np.linspace(-50,50,81)]
        for values in [points,points[::-1]]:
            r=section_bending({'edges':[{'index':0,'samples_3d':values}]},1)
            self.assertEqual(r['count_by_class'],{'convex_toward_+Z':75})
            self.assertFalse(r['inflection_brackets'])

    def test_responses_image_not_text(self):
        r=input_items([{'role':'user','content':[{'type':'text','text':'inspect'},{'type':'image_url','image_url':{'url':'data:image/png;base64,TEST','detail':'high'}}]}])
        self.assertEqual(r[0]['content'][1],{'type':'input_image','image_url':'data:image/png;base64,TEST','detail':'high'})

    def test_invalid_parameters_never_export(self):
        with tempfile.TemporaryDirectory() as temp:
            c=Controller(temp)
            with patch.object(c,'bridge') as bridge:
                for fractions in ([0],[-.1],[1],[True],[],[.1]*6,['.5']):
                    with self.assertRaises(ValueError):c.analyze_surface_sections(fractions=fractions)
                bridge.assert_not_called()


if __name__=='__main__':unittest.main()
