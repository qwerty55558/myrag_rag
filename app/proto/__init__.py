import os
import sys

# proto 생성 코드가 bare import (import rag_pb2)를 사용하므로
# 이 패키지 디렉토리를 sys.path에 추가하여 import 해결
_proto_dir = os.path.dirname(__file__)
if _proto_dir not in sys.path:
    sys.path.insert(0, _proto_dir)
