"""Static experiment safety unit tests; no real provider inference."""
import importlib.util,json,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("pdffast_lab_exp",ROOT/"scripts/experiment.py")
exp=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(exp)
class Test(unittest.TestCase):
    def test_real_input_fingerprint(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"image.png";p.write_bytes(b"first")
            hashes=exp.freeze_assets([{"input":str(p),"input_exists":True}])
            exp.validate_assets({"asset_sha256":hashes})
            p.write_bytes(b"changed")
            with self.assertRaises(ValueError):exp.validate_assets({"asset_sha256":hashes})
    def test_missing_plan_asset(self):
        with self.assertRaises(ValueError):
            exp.freeze_assets([{"input":"/missing/pdffast/image.png","input_exists":False}])
if __name__=="__main__":unittest.main()