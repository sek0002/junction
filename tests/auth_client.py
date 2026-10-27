"""Existing inventory tests exercise the app as a signed-in admin."""
from fastapi.testclient import TestClient
from app.auth import COOKIE, initial_pin_path


def bootstrap_pin():
    return initial_pin_path().read_text().strip()


class AuthenticatedClient(TestClient):
    def request(self,method,url,*args,**kwargs):
        if not self.cookies.get(COOKIE) and not str(url).startswith('/api/auth/'):
            result=super().request('POST','/api/auth/login',json={'username':'admin','pin':bootstrap_pin()})
            assert result.status_code==200,result.text
        return super().request(method,url,*args,**kwargs)
