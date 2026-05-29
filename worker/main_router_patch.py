"""
Temporary helper showing the required main.py router registration.

Add these two lines to worker/main.py:

from kickout_reference_api import router as kickout_reference_router

app.include_router(kickout_reference_router)

The import should sit with the other imports.
The include_router call should sit immediately after:

app = FastAPI(title='Gaelic Coach AI Worker')
"""
