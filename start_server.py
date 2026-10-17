import os
from pathlib import Path

import uvicorn


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent
    os.chdir(project_root)
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
