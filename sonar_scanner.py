import os
import requests
import time
import argparse
from datetime import datetime
from dotenv import load_dotenv
from plyer import notification
import sys

# Загружаем переменные окружения
load_dotenv()

# --- Конфигурация ---
ETHERSCAN_API_KEY = os.getenv('ETHERSCAN_API_KEY')
API_URL = 'https://api.etherscan.io/api'
# Адреса контрактов отслеживаемых токенов
WATCHED_TOKENS = {
    '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2': {'symbol': 'WETH', 'decimals': 18},
    '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48': {'symbol': 'USDC', 'decimals': 6},
    '0xdAC17F958D2ee523a2206206994597C13D831ec7': {'symbol': 'USDT', 'decimals': 6},
}

class ChainSonar:
    def __init__(self, eth_threshold, stable_threshold):
        if not ETHERSCAN_API_KEY:
            raise EnvironmentError("API-ключ ETHERSCAN_API_KEY не найден. Проверьте ваш .env файл.")
        
        self.eth_threshold = eth_threshold
        self.stable_threshold = stable_threshold
        self.session = requests.Session()
        self.targets = self.load_targets()
        self.last_seen_block = {}

    def load_targets(self):
        """Загружает адреса для отслеживания из файла whales.txt."""
        targets = {}
        try:
            with open('whales.txt', 'r') as f:
                for line in f:
                    if not line.strip() or line.startswith('#'):
                        continue
                    parts = [p.strip() for p in line.split(',')]
                    address = parts[0].lower()
                    name = parts[1] if len(parts) > 1 else address[:6] + '...' + address[-4:]
                    targets[address] = {'name': name}
                    self.last_seen_block[address] = None
            if not targets:
                raise FileNotFoundError
            self.log(f"Отслеживается {len(targets)} адресов.")
            return targets
        except FileNotFoundError:
            print("[!] Ошибка: файл 'whales.txt' не найден или пуст. Создайте его и добавьте адреса.", file=sys.stderr)
            sys.exit(1)

    def fetch_transactions(self, address):
        """Получает последние транзакции (нативные и токенов) для адреса."""
        # Для простоты отслеживаем и нативные ETH, и ERC20
        params = {
            'module': 'account',
            'action': 'txlist', # Для нативных ETH
            'address': address,
            'startblock': self.last_seen_block[address],
            'endblock': '99999999',
            'sort': 'desc',
            'apikey': ETHERSCAN_API_KEY
        }
        eth_txs = self.session.get(API_URL, params=params).json().get('result', [])
        
        params['action'] = 'tokentx' # Для токенов ERC20
        token_txs = self.session.get(API_URL, params=params).json().get('result', [])

        return (eth_txs or []) + (token_txs or [])

    def send_notification(self, title, message):
        """Отправляет системное уведомление."""
        try:
            notification.notify(title=title, message=message, app_name='ChainSonar', timeout=30)
        except Exception as e:
            print(f"[!] Не удалось отправить уведомление: {e}", file=sys.stderr)

    def log(self, message):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

    def run(self):
        """Основной цикл работы сканера."""
        self.log(f"📡 ChainSonar активирован.")
        self.log(f"Порог ETH: {self.eth_threshold}, Порог стейблов: {self.stable_threshold}.")

        try:
            while True:
                for address, data in self.targets.items():
                    txs = self.fetch_transactions(address)
                    if not txs:
                        continue
                    
                    # Обновляем последний виденный блок, чтобы не проверять старые транзакции
                    self.last_seen_block[address] = txs[0]['blockNumber']

                    for tx in txs:
                        # Нас интересуют только входящие транзакции
                        if tx['to'].lower() != address:
                            continue

                        is_native_eth = 'tokenSymbol' not in tx
                        amount = 0
                        symbol = ''
                        threshold = 0

                        if is_native_eth:
                            amount = int(tx['value']) / 10**18
                            symbol = 'ETH'
                            threshold = self.eth_threshold
                        else: # Это токен
                            token_addr = tx['contractAddress'].lower()
                            if token_addr in WATCHED_TOKENS:
                                token_info = WATCHED_TOKENS[token_addr]
                                amount = int(tx['value']) / 10**token_info['decimals']
                                symbol = token_info['symbol']
                                threshold = self.eth_threshold if symbol == 'WETH' else self.stable_threshold

                        if amount >= threshold:
                            self.log("🚨 ОБНАРУЖЕН СИГНАЛ!")
                            self.log(f"Кит: {data['name']} ({address[:6]}...{address[-4:]})")
                            self.log(f"Получил: {amount:.2f} {symbol}")
                            self.log(f"Tx: https://etherscan.io/tx/{tx['hash']}")
                            
                            title = f"📡 ChainSonar: Сигнал от {data['name']}!"
                            message = f"Обнаружен перевод {amount:.2f} {symbol}.\nКит, возможно, готовится к действию."
                            self.send_notification(title, message)
                            
                    time.sleep(2) # Небольшая пауза между запросами к разным кошелькам
                time.sleep(15) # Пауза между полными циклами проверки
        except KeyboardInterrupt:
            self.log("📡 ChainSonar деактивирован.")
            sys.exit(0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ChainSonar - проактивный сканер активности китов.")
    parser.add_argument("--eth-threshold", type=float, default=10.0, help="Порог для ETH/WETH.")
    parser.add_argument("--stable-threshold", type=float, default=20000.0, help="Порог для USDC/USDT.")
    
    args = parser.parse_args()
    
    try:
        sonar = ChainSonar(args.eth_threshold, args.stable_threshold)
        sonar.run()
    except (ValueError, EnvironmentError) as e:
        print(f"Ошибка инициализации: {e}", file=sys.stderr)
