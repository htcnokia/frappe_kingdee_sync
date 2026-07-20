./env/bin/pip install -e apps/kingdee_sync

bench --site site1.local install-app kingdee_sync

bench --site site1.local migrate

bench build

bench restart
