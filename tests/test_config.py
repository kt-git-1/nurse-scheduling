import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import config

def test_load_config():
    cfg = config.load_config()
    assert 'nurses' in cfg
    assert isinstance(cfg['nurses'], list)
    assert len(cfg['nurses']) > 0
