"""共享 HTTP session."""

import requests

session = requests.Session()
session.headers["User-Agent"] = "frp_pv_geo/1.0"
