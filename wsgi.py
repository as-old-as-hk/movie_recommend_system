import os
from app import create_app,db
from app.models import User,Role
from flask_migrate import Migrate,MigrateCommand
from flask_script import Manager, Shell

app=create_app(os.getenv('FLASK_CONFIG') or 'default')


if __name__ == '__main__':
	
    app.run()