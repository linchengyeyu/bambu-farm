import sys
import os

# 将 backend 目录加入 python path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

print("Attempting to import app.main...")
try:
    from app import main
    print("✅ Import successful! No NameErrors at module level.")
except ImportError as e:
    print(f"❌ ImportError: {e}")
except NameError as e:
    print(f"❌ NameError: {e}")
except Exception as e:
    print(f"❌ Unexpected error: {e}")
