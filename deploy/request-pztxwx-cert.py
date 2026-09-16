from __future__ import print_function

import json
import os
import sys


PANEL_ROOT = "/www/server/panel"
DOMAIN = "www.pztxwx.cn"
WEB_ROOT = "/www/wwwroot/www.pztxwx.cn"


def main():
    os.chdir(PANEL_ROOT)
    sys.path.insert(0, os.path.join(PANEL_ROOT, "class"))

    from acme_v2 import acme_v2

    client = acme_v2()
    result = client.apply_cert([DOMAIN], auth_type="http", auth_to=WEB_ROOT)
    if not result.get("status"):
        print(json.dumps({"status": False, "msg": result.get("msg")}, ensure_ascii=False))
        return 1

    client.set_crond()
    print(json.dumps({"status": True, "domain": DOMAIN, "save_path": result.get("save_path")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
