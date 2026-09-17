import sys,unittest,tempfile,hashlib,copy,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import numpy as np
from PIL import Image
import engine

class ProcessingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sample=Path(sys.argv[1]) if len(sys.argv)>1 else Path('astronaut.png')
        cls.rgb=engine.read_image(cls.sample)[0]
    def test_zero_is_identical(self):
        s=engine.fresh_state();self.assertTrue(np.array_equal(engine.process(self.rgb,s),self.rgb))
    def test_multi_face_and_exclusion(self):
        rgb=np.concatenate([self.rgb,self.rgb],axis=1);faces=engine.detect_faces(rgb)
        self.assertGreaterEqual(len(faces),2)
        s=engine.fresh_state();s['faces']=faces;s['settings']=[70,70,70,70]
        faces[0]['enabled']=False;m=engine.skin_mask(rgb,s)
        f=faces[0]['box'];x=int((f[0]+f[2]/2)*rgb.shape[1]);y=int((f[1]+f[3]/2)*rgb.shape[0]);self.assertEqual(m[y,x],0)
        self.assertGreater(float(m.max()),.1)
    def test_brush_and_each_slider(self):
        rng=np.random.default_rng(3);rgb=np.clip(rng.normal(145,24,(256,256,3)),0,255).astype(np.uint8)
        s=engine.fresh_state();s['faces']=[];s['strokes']=[{'points':[[.5,.5]],'size':.4,'erase':False}]
        for i in range(4):
            s['settings']=[0]*4;s['settings'][i]=100;out=engine.retouch(rgb,s)
            self.assertFalse(np.array_equal(out[110:145,110:145],rgb[110:145,110:145]))
            self.assertTrue(np.array_equal(out[:25,:25],rgb[:25,:25]))
    def test_inpaint_locality(self):
        rgb=np.full((160,160,3),150,np.uint8);rgb[75:85,75:85]=0
        strokes=[{'points':[[.5,.5]],'size':.17,'erase':False}]
        out=engine.remove_objects(rgb,[strokes]);self.assertGreater(out[80,80,0],120);self.assertTrue(np.array_equal(out[:30],rgb[:30]))
    def test_save_no_overwrite_dimensions_orientation(self):
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'اختبار.jpg';exif=Image.Exif();exif[274]=6
            Image.fromarray(self.rgb[:200,:300]).save(src,exif=exif)
            digest=hashlib.sha256(src.read_bytes()).hexdigest();rgb,meta=engine.read_image(src)
            self.assertEqual(rgb.shape[:2],(300,200))
            a=engine.save_new(rgb,src,d,meta);b=engine.save_new(rgb,src,d,meta);c=engine.save_new(rgb,src,d,meta,'PNG')
            self.assertNotEqual(a,b);self.assertEqual(hashlib.sha256(src.read_bytes()).hexdigest(),digest)
            for p in [a,b,c]:
                with Image.open(p) as im:self.assertEqual(im.size,(200,300));self.assertNotEqual(im.getexif().get(274),6)
            self.assertTrue(np.array_equal(np.array(Image.open(c)),rgb))
    def test_background_model(self):
        start=time.time();alpha=engine.person_alpha(self.rgb)
        self.assertEqual(alpha.shape,self.rgb.shape[:2]);self.assertTrue(np.isfinite(alpha).all());self.assertGreater(alpha.max(),.9);self.assertLess(alpha.min(),.1)
        # Astronaut's torso is foreground; far upper-left background is not.
        self.assertGreater(float(alpha[350,240]),.7)
        with tempfile.TemporaryDirectory() as d:
            bg=Path(d)/'bg.png';Image.new('RGB',(300,200),(30,150,200)).save(bg)
            out=engine.replace_background(self.rgb,bg);self.assertEqual(out.shape,self.rgb.shape)
            Image.fromarray(out).save(Path(__file__).parents[1]/'background-test.png')
        print('Background inference seconds:',round(time.time()-start,2))

if __name__=='__main__':
    sample=sys.argv[1] if len(sys.argv)>1 else 'astronaut.png'
    ProcessingTests.sample=Path(sample)
    # Preserve sample arg for setUpClass, avoid unittest parsing it.
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(ProcessingTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(not result.wasSuccessful())
