from main import app

try:
    from cv_integration import cv_status
except Exception:
    def cv_status():
        return {
            'enabled': False,
            'phase': 'player_detection_team_colour_shape',
            'reason': 'cv_integration module unavailable'
        }


@app.get('/cv-status')
def get_cv_status():
    return cv_status()
