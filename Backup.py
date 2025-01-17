import os
import subprocess
import datetime
import mysql.connector
from dotenv import load_dotenv
from mega import Mega
import pyminizip
# import zipfile
# заархивировать файлы
#  zip -r -9 billing_configs.zip /home/user/scripts/Backup/billing/

# Загружаем переменные окружения из файла .env
load_dotenv()

# Настройки базы данных и путей
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_NAMES = [os.getenv('DB_NAME'), os.getenv('DB_PAY_NAME')]  # Список баз данных
SITE_FOLDER = os.getenv('SITE_FOLDER')
BACKUP_DIR = '/home/user/scripts/Backup'
ARCHIVE_NAME = os.path.join(BACKUP_DIR, f"backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.zip")
ZIP_PASSWORD = os.getenv('ZIP_PASSWORD')
LOG_FILE = os.path.join(BACKUP_DIR, 'backup.log')  # Файл для записи логов

# Учетные данные для mega.nz
MEGA_EMAIL = os.getenv('MEGA_EMAIL')
MEGA_PASSWORD = os.getenv('MEGA_PASSWORD')
MEGA_FOLDER = 'Happylink'

# Функция для записи в лог с текущей датой и временем
def write_log(message):
    with open(LOG_FILE, 'a') as log_file:
        log_file.write(f"--\n{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")

# Функция для удаления старого бэкапа для каждой базы данных
def delete_old_backups(db_names):
    try:
        for db_name in db_names:
            backup_files = os.listdir(BACKUP_DIR)
            db_backup_files = [f for f in backup_files if f.startswith(db_name) and f.endswith('.sql')]
            
            if db_backup_files:
                old_backup = max([os.path.join(BACKUP_DIR, f) for f in db_backup_files], key=os.path.getctime)
                os.remove(old_backup)
                write_log(f"Старый бэкап для {db_name} ({old_backup}) удален.")
            else:
                write_log(f"Старый бэкап для {db_name} не найден.")
                
    except Exception as e:
        write_log(f"Ошибка при удалении старых бэкапов: {e}")

# Функция для очистки таблицы system_events
def truncate_table():
    try:
        connection = mysql.connector.connect(
            host='localhost',
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAMES[0]
        )
        cursor = connection.cursor()
        cursor.execute("TRUNCATE TABLE system_events;")
        connection.commit()
        write_log("Таблица system_events очищена.")
    except mysql.connector.Error as err:
        write_log(f"Ошибка: {err}")
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

# Функция для создания дампов баз данных
def create_backup(db_names):
    backup_files = [SITE_FOLDER]
    for db_name in db_names:
        backup_file = os.path.join(BACKUP_DIR, f"{db_name}_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.sql")
        backup_files.append(backup_file)
        
        result = subprocess.run(f"mysqldump -u {DB_USER} -p{DB_PASSWORD} --routines --triggers {db_name} > {backup_file}", shell=True)
        
        if result.returncode == 0:
            write_log(f"Дамп базы данных {db_name} успешно сохранен в {backup_file}")
        else:
            write_log(f"Ошибка при создании дампа базы данных {db_name}")
    
    #print(backup_files)
    return backup_files

# Функция для архивирования файлов
def archive_backup_files(backup_files, password=ZIP_PASSWORD):
    try:
        for backup_file in backup_files:
            # Создаём архив сразу для всех файлов
            pyminizip.compress_multiple(backup_files, [], ARCHIVE_NAME, password, 5)
        
        write_log(f"Файлы успешно заархивированы в {ARCHIVE_NAME} с паролем")
    except Exception as e:
        write_log(f"Ошибка при архивировании файлов: {e}")

# Функция для загрузки архива на mega.nz и добавления ссылки в лог
def upload_to_mega(archive_name):
    try:
        # Initialize Mega instance and log in
        mega = Mega()
        m = mega.login(MEGA_EMAIL, MEGA_PASSWORD)
        
        # Find or create the 'Happylink' folder
        folder_name = MEGA_FOLDER
        folder = None
        folders = m.get_files()
        
        # Check if the folder exists
        for file_id, details in folders.items():
            if details['a'].get('n') == folder_name and details['t'] == 1:
                folder = details
                break
        
        # If the folder doesn't exist, create it
        if folder is None:
            folder = m.create_folder(folder_name)
            folder_id = folder[0]['f'][0]['h']
        else:
            folder_id = folder['h']
        
        # Upload the file to the 'Happylink' folder
        file = m.upload(archive_name, folder_id)
        public_link = m.get_upload_link(file)
        
        # Log the success message with the public link
        write_log(f"Архив {archive_name} успешно загружен в папку {folder_name} на mega.nz. \n Ссылка: {public_link}")
    
    except Exception as e:
        # Log the error if something goes wrong
        write_log(f"Ошибка при загрузке архива на mega.nz: {e}")

# Основная логика выполнения
if __name__ == "__main__":
    delete_old_backups(DB_NAMES)  # Удаление старых бэкапов для всех баз данных
    truncate_table()  # Очистка таблицы system_events (в первой базе данных)
    backup_files = create_backup(DB_NAMES)  # Создание новых бэкапов для всех баз данных
    archive_backup_files(backup_files)  # Архивирование бэкапов
    upload_to_mega(ARCHIVE_NAME)  # Загрузка архива на mega.nz
