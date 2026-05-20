# Vercel serverless entry point
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server import app

# Vercel нужен handler
handler = app
