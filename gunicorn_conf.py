import multiprocessing
bind = "127.0.0.1:8000"
workers = max(2, multiprocessing.cpu_count() // 2)
timeout = 60
graceful_timeout = 30
accesslog = "/home/z/z/logs/gunicorn.access.log"
errorlog = "/home/z/z/logs/gunicorn.error.log"
loglevel = "info"