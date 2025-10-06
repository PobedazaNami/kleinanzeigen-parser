#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Kleinanzeigen Parser - Production Entry Point
Парсер объявлений Kleinanzeigen и Immowelt для поиска квартир в аренду
"""

import logging
from logging.handlers import RotatingFileHandler
import sys
import os
import json
import time
import signal
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from typing import Dict, List

# Добавляем текущую директорию в PYTHONPATH
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from kleinanzeigen_parser import KleinanzeigenParser
from immowelt_parser import ImmoweltParser

class ProductionRunner:
    """Класс для запуска парсера в продакшене"""
    
    def __init__(self):
        self.parsers = []  # Список парсеров для разных сайтов
        self.logger = None
        self.running = True
        self.setup_logging()
        self.setup_signal_handlers()
        
    def setup_logging(self):
        """Настройка системы логирования"""
        # Создаем папку для логов
        logs_dir = Path(__file__).parent / "logs"
        logs_dir.mkdir(exist_ok=True)
        
        # Настраиваем root logger
        self.logger = logging.getLogger("kleinanzeigen_parser")
        self.logger.setLevel(logging.INFO)
        
        # Очищаем существующие обработчики
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)
        
        # Форматтер для логов
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Файловый обработчик с ротацией (главный лог)
        file_handler = RotatingFileHandler(
            logs_dir / "parser.log",
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)
        
        # Файловый обработчик для ошибок
        error_handler = RotatingFileHandler(
            logs_dir / "errors.log",
            maxBytes=5*1024*1024,   # 5MB
            backupCount=3,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(formatter)
        self.logger.addHandler(error_handler)
        
        # Консольный обработчик
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        ))
        self.logger.addHandler(console_handler)
        
        # Настраиваем логгеры для внешних библиотек
        logging.getLogger("requests").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("telegram").setLevel(logging.WARNING)
        
        self.logger.info("="*60)
        self.logger.info("Система логирования инициализирована")
        self.logger.info(f"Логи сохраняются в: {logs_dir}")
        self.logger.info("="*60)
    
    def setup_signal_handlers(self):
        """Настройка обработчиков сигналов для корректного завершения"""
        def signal_handler(signum, frame):
            self.logger.info(f"Получен сигнал {signum}, завершение работы...")
            self.running = False
            
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    def validate_config(self, config_path="config.json"):
        """Валидация конфигурации перед запуском"""
        self.logger.info("Проверка конфигурации...")
        
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Файл конфигурации {config_path} не найден")
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Ошибка в JSON конфигурации: {e}")
        
        # Проверяем обязательные параметры
        required_params = {
            'search_urls': list,
            'telegram': dict,
            'filters': dict,
            'database': dict,
            'monitoring': dict,
            'date_filtering': dict
        }
        
        for param, expected_type in required_params.items():
            if param not in config:
                raise ValueError(f"Отсутствует обязательный параметр: {param}")
            if not isinstance(config[param], expected_type):
                raise ValueError(f"Неверный тип параметра {param}: ожидается {expected_type.__name__}")
        
        # Проверяем Telegram конфигурацию
        telegram_config = config['telegram']
        if not telegram_config.get('bot_token'):
            raise ValueError("Отсутствует telegram.bot_token")
        if not telegram_config.get('chat_id'):
            raise ValueError("Отсутствует telegram.chat_id")
        
        # Проверяем URL'ы для поиска
        if not config['search_urls']:
            raise ValueError("Список search_urls пуст")
        
        self.logger.info("✓ Конфигурация валидна")
        return config
    
    def detect_site_type(self, url: str) -> str:
        """Определение типа сайта по URL"""
        parsed_url = urlparse(url)
        domain = parsed_url.netloc.lower()
        
        if 'kleinanzeigen.de' in domain or 'ebay-kleinanzeigen.de' in domain:
            return 'kleinanzeigen'
        elif 'immowelt.de' in domain:
            return 'immowelt'
        else:
            self.logger.warning(f"Неизвестный тип сайта для URL: {url}, используем kleinanzeigen по умолчанию")
            return 'kleinanzeigen'
    
    def group_urls_by_site(self, urls: List[str]) -> Dict[str, List[str]]:
        """Группировка URL по типам сайтов"""
        grouped = {
            'kleinanzeigen': [],
            'immowelt': []
        }
        
        for url in urls:
            site_type = self.detect_site_type(url)
            grouped[site_type].append(url)
        
        return grouped
    
    def check_dependencies(self):
        """Проверка зависимостей"""
        self.logger.info("Проверка зависимостей...")
        
        required_modules = [
            'requests', 'bs4', 'telegram', 'schedule', 
            'sqlite3', 'lxml', 'urllib3'
        ]
        
        missing_modules = []
        for module in required_modules:
            try:
                __import__(module)
            except ImportError:
                missing_modules.append(module)
        
        if missing_modules:
            raise ImportError(f"Отсутствуют модули: {', '.join(missing_modules)}")
        
        self.logger.info("✓ Все зависимости установлены")
    
    def run(self):
        """Главная функция запуска"""
        try:
            self.logger.info("🚀 Запуск Multi-Site Parser в продакшен режиме")
            self.logger.info(f"Время запуска: {datetime.now()}")
            self.logger.info(f"Python версия: {sys.version}")
            self.logger.info(f"Рабочая директория: {os.getcwd()}")
            
            # Проверяем зависимости
            self.check_dependencies()
            
            # Валидируем конфигурацию
            config = self.validate_config()
            
            # Группируем URL по типам сайтов
            grouped_urls = self.group_urls_by_site(config['search_urls'])
            
            # Создаем парсеры для каждого типа сайта
            self.parsers = []
            
            if grouped_urls['kleinanzeigen']:
                self.logger.info(f"Создание парсера для Kleinanzeigen ({len(grouped_urls['kleinanzeigen'])} URL)")
                kleinanzeigen_config = config.copy()
                kleinanzeigen_config['search_urls'] = grouped_urls['kleinanzeigen']
                
                # Сохраняем временный конфиг для kleinanzeigen
                with open('config_kleinanzeigen_temp.json', 'w', encoding='utf-8') as f:
                    json.dump(kleinanzeigen_config, f, ensure_ascii=False, indent=2)
                
                kleinanzeigen_parser = KleinanzeigenParser("config_kleinanzeigen_temp.json")
                self.parsers.append(('Kleinanzeigen', kleinanzeigen_parser))
            
            if grouped_urls['immowelt']:
                self.logger.info(f"Создание парсера для Immowelt ({len(grouped_urls['immowelt'])} URL)")
                immowelt_config = config.copy()
                immowelt_config['search_urls'] = grouped_urls['immowelt']
                
                # Сохраняем временный конфиг для immowelt
                with open('config_immowelt_temp.json', 'w', encoding='utf-8') as f:
                    json.dump(immowelt_config, f, ensure_ascii=False, indent=2)
                
                immowelt_parser = ImmoweltParser("config_immowelt_temp.json")
                self.parsers.append(('Immowelt', immowelt_parser))
            
            if not self.parsers:
                raise ValueError("Не создано ни одного парсера. Проверьте URL в конфигурации.")
            
            # Тестируем подключение к Telegram через первый парсер
            self.logger.info("Тестирование Telegram подключения...")
            test_message = f"🟢 Multi-Site Parser запущен\nСайты: {', '.join([name for name, _ in self.parsers])}\nВремя: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            self.parsers[0][1].send_telegram_sync(test_message)
            
            self.logger.info("✓ Парсеры успешно инициализированы")
            self.logger.info("📡 Начинаем мониторинг объявлений...")
            
            # Запускаем основной цикл
            while self.running:
                try:
                    self.logger.info("--- Начало цикла парсинга ---")
                    start_time = time.time()
                    
                    # Запускаем все парсеры
                    for site_name, parser in self.parsers:
                        try:
                            self.logger.info(f"🔄 Парсинг {site_name}...")
                            parser.parse_listings()
                        except Exception as e:
                            self.logger.error(f"Ошибка при парсинге {site_name}: {e}", exc_info=True)
                    
                    execution_time = time.time() - start_time
                    self.logger.info(f"--- Цикл завершен за {execution_time:.2f} сек ---")
                    
                    # Ждем 30 минут до следующего запуска
                    if self.running:
                        self.logger.info("⏰ Ожидание 30 минут до следующего запуска...")
                        for i in range(1800):  # 30 * 60 = 1800 секунд
                            if not self.running:
                                break
                            time.sleep(1)
                            
                            # Показываем прогресс каждые 5 минут
                            if i % 300 == 0 and i > 0:
                                remaining_minutes = (1800 - i) // 60
                                self.logger.info(f"⏳ Осталось {remaining_minutes} минут до следующего запуска")
                    
                except KeyboardInterrupt:
                    self.logger.info("Получено прерывание от пользователя")
                    break
                except Exception as e:
                    self.logger.error(f"Ошибка в главном цикле: {e}", exc_info=True)
                    
                    # Отправляем уведомление об ошибке
                    try:
                        error_message = f"🔴 Ошибка в главном цикле парсера:\n{str(e)}"
                        if self.parsers:
                            self.parsers[0][1].send_telegram_sync(error_message)
                    except:
                        pass
                    
                    # Ждем 5 минут перед повторной попыткой
                    self.logger.info("⏰ Ожидание 5 минут перед повторной попыткой...")
                    time.sleep(300)
        
        except Exception as e:
            self.logger.error(f"Критическая ошибка при запуске: {e}", exc_info=True)
            
            # Пытаемся отправить уведомление о критической ошибке
            try:
                if self.parsers:
                    error_message = f"🔴 КРИТИЧЕСКАЯ ОШИБКА при запуске парсера:\n{str(e)}"
                    self.parsers[0][1].send_telegram_sync(error_message)
            except:
                pass
                
            sys.exit(1)
        
        finally:
            self.logger.info("🛑 Завершение работы парсера")
            
            # Отправляем уведомление о завершении
            try:
                if self.parsers:
                    shutdown_message = f"⚪ Multi-Site Parser остановлен\nВремя: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    self.parsers[0][1].send_telegram_sync(shutdown_message)
            except:
                pass
            
            # Удаляем временные конфиги
            for temp_config in ['config_kleinanzeigen_temp.json', 'config_immowelt_temp.json']:
                if os.path.exists(temp_config):
                    os.remove(temp_config)
    
    def run_single(self):
        """Выполнить один цикл парсинга и завершить"""
        try:
            self.logger.info("🚀 Запуск Multi-Site Parser в single-run режиме")
            self.logger.info(f"Время запуска: {datetime.now()}")
            self.logger.info(f"Python версия: {sys.version}")
            self.logger.info(f"Рабочая директория: {os.getcwd()}")
            
            # Проверка зависимостей
            self.logger.info("Проверка зависимостей...")
            self.check_dependencies()
            self.logger.info("✓ Все зависимости установлены")
            
            # Валидация конфигурации
            self.logger.info("Проверка конфигурации...")
            config = self.validate_config()
            self.logger.info("✓ Конфигурация валидна")
            
            # Группируем URL по типам сайтов
            grouped_urls = self.group_urls_by_site(config['search_urls'])
            
            # Создаем парсеры для каждого типа сайта
            self.parsers = []
            
            if grouped_urls['kleinanzeigen']:
                self.logger.info(f"Создание парсера для Kleinanzeigen ({len(grouped_urls['kleinanzeigen'])} URL)")
                kleinanzeigen_config = config.copy()
                kleinanzeigen_config['search_urls'] = grouped_urls['kleinanzeigen']
                
                with open('config_kleinanzeigen_temp.json', 'w', encoding='utf-8') as f:
                    json.dump(kleinanzeigen_config, f, ensure_ascii=False, indent=2)
                
                kleinanzeigen_parser = KleinanzeigenParser("config_kleinanzeigen_temp.json")
                self.parsers.append(('Kleinanzeigen', kleinanzeigen_parser))
            
            if grouped_urls['immowelt']:
                self.logger.info(f"Создание парсера для Immowelt ({len(grouped_urls['immowelt'])} URL)")
                immowelt_config = config.copy()
                immowelt_config['search_urls'] = grouped_urls['immowelt']
                
                with open('config_immowelt_temp.json', 'w', encoding='utf-8') as f:
                    json.dump(immowelt_config, f, ensure_ascii=False, indent=2)
                
                immowelt_parser = ImmoweltParser("config_immowelt_temp.json")
                self.parsers.append(('Immowelt', immowelt_parser))
            
            if not self.parsers:
                raise ValueError("Не создано ни одного парсера. Проверьте URL в конфигурации.")
            
            # Тестируем подключение к Telegram
            self.logger.info("Тестирование Telegram подключения...")
            test_message = f"🟢 Multi-Site Parser запущен (single-run)\nСайты: {', '.join([name for name, _ in self.parsers])}\nВремя: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            self.parsers[0][1].send_telegram_sync(test_message)
            
            self.logger.info("✓ Парсеры успешно инициализированы")
            self.logger.info("📡 Выполняем один цикл парсинга...")
            
            # Выполняем один цикл
            self.logger.info("--- Начало цикла парсинга ---")
            start_time = time.time()
            
            # Запускаем все парсеры
            for site_name, parser in self.parsers:
                try:
                    self.logger.info(f"🔄 Парсинг {site_name}...")
                    parser.parse_listings()
                except Exception as e:
                    self.logger.error(f"Ошибка при парсинге {site_name}: {e}", exc_info=True)
            
            elapsed_time = time.time() - start_time
            self.logger.info(f"--- Цикл завершен за {elapsed_time:.2f} сек ---")
            self.logger.info("✅ Single-run завершен успешно")
            
        except Exception as e:
            self.logger.error(f"Критическая ошибка: {e}", exc_info=True)
            
            # Пытаемся отправить уведомление о критической ошибке
            try:
                if self.parsers:
                    error_message = f"🔴 ОШИБКА в single-run режиме:\n{str(e)}"
                    self.parsers[0][1].send_telegram_sync(error_message)
            except:
                pass
                
            sys.exit(1)
        
        finally:
            self.logger.info("🛑 Single-run завершен")
            
            # Удаляем временные конфиги
            for temp_config in ['config_kleinanzeigen_temp.json', 'config_immowelt_temp.json']:
                if os.path.exists(temp_config):
                    os.remove(temp_config)


def main():
    """Главная точка входа"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Multi-Site Apartment Parser (Kleinanzeigen + Immowelt)')
    parser.add_argument('--single-run', action='store_true', 
                       help='Выполнить только один цикл парсинга и выйти')
    args = parser.parse_args()
    
    if args.single_run:
        print("Multi-Site Parser - Single Run Mode")
    else:
        print("Multi-Site Parser - Production Mode")
    print("=" * 50)
    
    try:
        runner = ProductionRunner()
        if args.single_run:
            runner.run_single()
        else:
            runner.run()
    except KeyboardInterrupt:
        print("\nПолучено прерывание от пользователя. Завершение...")
    except Exception as e:
        print(f"Критическая ошибка: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()