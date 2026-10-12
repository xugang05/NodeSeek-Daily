# -- coding: utf-8 --
"""
Copyright (c) 2024 [Hosea]
Licensed under the MIT License.
See LICENSE file in the project root for full license information.
"""
import os
import re
import shutil
import subprocess
import sys
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import random
import time
import traceback
import undetected_chromedriver as uc
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

ns_random_env = os.environ.get("NS_RANDOM", "false")
ns_random = ns_random_env.lower() == "true"
cookie = os.environ.get("NS_COOKIE") or os.environ.get("COOKIE")
# 通过环境变量控制是否使用无头模式，默认为 True（无头模式）
headless = os.environ.get("HEADLESS", "true").lower() == "true"

randomInputStr = ["bd","绑定","帮顶"]

NODESEEK_ORIGIN = "https://www.nodeseek.com"
ALREADY_CHECKED_IN = "今天已完成签到，请勿重复操作"


class CheckinError(RuntimeError):
    """An actionable, safe-to-log failure (never contains cookies/page content)."""


def check_page(driver, allow_login=False):
    """Do not submit requests from a redirect, login page or security challenge."""
    location = urlsplit(driver.current_url)
    if (location.scheme, location.netloc) != ("https", "www.nodeseek.com"):
        raise CheckinError("unexpected_origin: 页面不在 NodeSeek，请检查访问状态")
    title = driver.title.lower()
    if any(marker in title for marker in ("just a moment", "attention required", "security verification")):
        raise CheckinError("challenge: NodeSeek 要求人机验证，未执行签到")
    if driver.find_elements(By.CSS_SELECTOR, "#challenge-form, #challenge-running, iframe[src*='challenges.cloudflare.com']"):
        raise CheckinError("challenge: NodeSeek 要求人机验证，未执行签到")
    if not allow_login and location.path.rstrip("/") in ("/signIn", "/signin", "/login"):
        raise CheckinError("unauthenticated: 页面跳转到登录页，请更新 NS_COOKIE")


# Use the site's same-origin attendance endpoint in the existing browser session.
# No raw Cookie header, token, response body or account details are written to logs.
ATTENDANCE_SCRIPT = r"""
const randomReward = arguments[0];
const done = arguments[arguments.length - 1];
const controller = new AbortController();
const timer = setTimeout(() => controller.abort(), 20000);
(async () => {
    try {
        const response = await fetch('/api/attendance?random=' + randomReward, {
            method: 'POST',
            credentials: 'same-origin',
            redirect: 'error',
            headers: {'Accept': 'application/json', 'Content-Type': 'application/json'},
            body: JSON.stringify({random: randomReward === 'true'}),
            signal: controller.signal
        });
        const raw = await response.text();
        let data = null;
        try { data = JSON.parse(raw); } catch (_) {}
        done({status: response.status, data,
              challenge: /just a moment|cf-chl-|challenge-platform|verify you are human/i.test(raw)});
    } catch (error) {
        done({error: error.name === 'AbortError' ? 'timeout' : 'network_or_redirect'});
    } finally {
        clearTimeout(timer);
    }
})();
"""


def interpret_attendance(response):
    """Only an explicit server confirmation counts as a completed check-in."""
    if not isinstance(response, dict):
        raise CheckinError("invalid_response: 签到接口没有返回有效结果")
    if response.get("error"):
        raise CheckinError("request_failed: 签到请求超时、网络错误或重定向，结果未确认")
    if response.get("challenge") is True:
        raise CheckinError("challenge: 签到接口要求人机验证，结果未确认")
    status = response.get("status")
    if status == 401:
        raise CheckinError("unauthenticated: 登录已失效，请更新 NS_COOKIE")
    if type(status) is not int or not 200 <= status < 300:
        safe_status = status if type(status) is int else "unknown"
        raise CheckinError(f"http_error: 签到接口 HTTP {safe_status}，结果未确认")
    data = response.get("data")
    if not isinstance(data, dict):
        raise CheckinError("invalid_response: 签到接口返回非 JSON 对象，结果未确认")
    message = data.get("message")
    if isinstance(message, str) and any(word in message for word in ("未登录", "请先登录", "登录过期", "登录失效", "用户不存在")):
        raise CheckinError("unauthenticated: 服务端未识别登录状态，请检查 NS_COOKIE")
    if data.get("success") is True:
        return "success"
    # Exact server response, not a substring found in page text or arbitrary errors.
    if isinstance(message, str) and message.strip().rstrip("。！!") == ALREADY_CHECKED_IN:
        return "already_checked_in"
    raise CheckinError("rejected: 服务端未确认签到成功或今日已签到，请检查登录状态及站点限制")


def click_sign_icon(driver):
    """Compatibility entry point: submit and verify attendance, without brittle UI text."""
    try:
        print("访问 NodeSeek 签到页面...")
        driver.get(NODESEEK_ORIGIN + "/board")
        check_page(driver)
        random_reward = os.environ.get("NS_RANDOM", "false").lower() == "true"
        print(f"签到奖励模式: {'随机' if random_reward else '固定'}")
        driver.set_script_timeout(25)
        response = driver.execute_async_script(ATTENDANCE_SCRIPT, str(random_reward).lower())
        result = interpret_attendance(response)
        if result == "success":
            print("签到成功：服务端已确认 (checkin_status=success)")
            gain = response["data"].get("gain")
            if type(gain) is int:
                print(f"本次获得鸡腿: {gain}")
        else:
            print("今日已签到：服务端已确认 (checkin_status=already_checked_in)")
        return True
    except CheckinError as error:
        print(f"签到失败 (checkin_status=failed): {error}")
        return False
    except Exception as error:
        # Selenium errors may include page content or session details; log type only.
        print(f"签到失败 (checkin_status=failed): browser_error/{type(error).__name__}，结果未确认")
        return False


def resolve_chrome_binary():
    """返回同一个 Chrome/Chromium 可执行文件的路径和主版本号。"""
    for name in ("google-chrome", "chromium-browser", "google-chrome-stable", "chromium"):
        executable = shutil.which(name)
        if not executable:
            continue
        executable = os.path.abspath(executable)
        try:
            output = subprocess.check_output(
                [executable, "--version"],
                stderr=subprocess.STDOUT,
                text=True,
                timeout=10,
            )
            match = re.search(
                r"(?m)^\s*(?:Google Chrome(?: for Testing)?|Chromium)\s+(\d+)\.\d+\.\d+",
                output,
            )
            if match and int(match.group(1)) > 0:
                return executable, int(match.group(1))
        except (OSError, subprocess.SubprocessError):
            continue
    raise RuntimeError("找不到可用的 Chrome/Chromium，或无法读取浏览器版本号")


def create_browser(headless=True):
    """只启动浏览器，不访问 NodeSeek 或读取、设置 Cookie。"""
    print("开始初始化浏览器...")
    executable, major_version = resolve_chrome_binary()
    options = uc.ChromeOptions()
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')

    if headless:
        print("启用无头模式...")
        options.add_argument('--headless')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')

    print(f"正在启动 Chrome: {executable}，主版本号: {major_version}")
    driver = uc.Chrome(
        options=options,
        browser_executable_path=executable,
        version_main=major_version,
    )

    if headless:
        driver.set_window_size(1920, 1080)

    print("Chrome启动成功")
    return driver

def setup_driver_and_cookies():
    """Initialize the browser; fail closed if any configured cookie cannot be set."""
    driver = None
    try:
        raw_cookie = os.environ.get("NS_COOKIE") or os.environ.get("COOKIE")
        if not raw_cookie or not raw_cookie.strip():
            raise CheckinError("missing_cookie: 未找到 NS_COOKIE 配置")
        cookies = []
        for part in raw_cookie.split(";"):
            if not part.strip():
                continue
            name, separator, value = part.strip().partition("=")
            if not separator or not name:
                raise CheckinError("invalid_cookie: Cookie 格式无效，请使用请求中的 Cookie 值")
            cookies.append({"name": name, "value": value, "domain": ".nodeseek.com", "path": "/"})
        if not cookies:
            raise CheckinError("invalid_cookie: 没有有效 Cookie")
        driver = create_browser(headless=os.environ.get("HEADLESS", "true").lower() == "true")
        driver.set_page_load_timeout(45)
        driver.get(NODESEEK_ORIGIN)
        check_page(driver, allow_login=True)
        for item in cookies:
            driver.add_cookie(item)
        driver.get(NODESEEK_ORIGIN)
        check_page(driver)
        return driver
    except Exception as error:
        if isinstance(error, CheckinError):
            print(f"初始化失败: {error}")
        else:
            print(f"初始化失败: browser_or_cookie_error/{type(error).__name__}")
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
        return None


def nodeseek_comment(driver):
    try:
        print("正在访问交易区...")
        target_url = 'https://www.nodeseek.com/categories/trade'
        driver.get(target_url)
        print("等待页面加载...")
        
        # 获取初始帖子列表
        posts = WebDriverWait(driver, 30).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, '.post-list-item'))
        )
        print(f"成功获取到 {len(posts)} 个帖子")
        
        # 过滤掉置顶帖
        valid_posts = [post for post in posts if not post.find_elements(By.CSS_SELECTOR, '.pined')]
        selected_posts = random.sample(valid_posts, min(20, len(valid_posts)))
        
        # 存储已选择的帖子URL
        selected_urls = []
        for post in selected_posts:
            try:
                post_link = post.find_element(By.CSS_SELECTOR, '.post-title a')
                selected_urls.append(post_link.get_attribute('href'))
            except:
                continue
        
        is_chicken_leg = False
        
        # 使用URL列表进行操作
        for i, post_url in enumerate(selected_urls):
            try:
                print(f"正在处理第 {i+1} 个帖子")
                driver.get(post_url)
                
                # 处理加鸡腿
                if is_chicken_leg is False:
                    is_chicken_leg = click_chicken_leg(driver)
                
                # 等待 CodeMirror 编辑器加载
                editor = WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '.CodeMirror'))
                )
                
                # 点击编辑器区域获取焦点
                editor.click()
                time.sleep(0.5)
                input_text = random.choice(randomInputStr)

                # 模拟输入
                actions = ActionChains(driver)
                # 随机输入 randomInputStr
                for char in input_text:
                    actions.send_keys(char)
                    actions.pause(random.uniform(0.1, 0.3))
                actions.perform()
                
                # 等待一下确保内容已经输入
                time.sleep(2)
                
                # 使用更精确的选择器定位提交按钮
                submit_button = WebDriverWait(driver, 30).until(
                 EC.element_to_be_clickable((By.XPATH, "//button[contains(@class, 'submit') and contains(@class, 'btn') and contains(text(), '发布评论')]"))
                )
                # 确保按钮可见并可点击
                driver.execute_script("arguments[0].scrollIntoView(true);", submit_button)
                time.sleep(0.5)
                submit_button.click()
                
                print(f"已在帖子 {post_url} 中完成评论")
                
                # 返回交易区
                # driver.get(target_url)
                # time.sleep(2)  # 等待页面加载
                time.sleep(random.uniform(2,5))
                
            except Exception as e:
                print(f"处理帖子时出错: {str(e)}")
                continue
                
        print("NodeSeek评论任务完成")
                
    except Exception as e:
        print(f"NodeSeek评论出错: {str(e)}")
        print("详细错误信息:")
        print(traceback.format_exc())

def click_chicken_leg(driver):
    try:
        print("尝试点击加鸡腿按钮...")
        chicken_btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, '//div[@class="nsk-post"]//div[@title="加鸡腿"][1]'))
        )
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", chicken_btn)
        time.sleep(0.5)
        chicken_btn.click()
        print("加鸡腿按钮点击成功")
        
        # 等待确认对话框出现
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '.msc-confirm'))
        )
        
        # 检查是否是7天前的帖子
        try:
            error_title = driver.find_element(By.XPATH, "//h3[contains(text(), '该评论创建于7天前')]")
            if error_title:
                print("该帖子超过7天，无法加鸡腿")
                ok_btn = driver.find_element(By.CSS_SELECTOR, '.msc-confirm .msc-ok')
                ok_btn.click()
                return False
        except:
            ok_btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, '.msc-confirm .msc-ok'))
            )
            ok_btn.click()
            print("确认加鸡腿成功")
            
        # 等待确认对话框消失
        WebDriverWait(driver, 5).until_not(
            EC.presence_of_element_located((By.CSS_SELECTOR, '.msc-overlay'))
        )
        time.sleep(1)  # 额外等待以确保对话框完全消失
        
        return True
        
    except Exception as e:
        print(f"加鸡腿操作失败: {str(e)}")
        return False

def main():
    print("开始执行 NodeSeek 签到...")
    driver = setup_driver_and_cookies()
    if driver is None:
        return 1
    try:
        return 0 if click_sign_icon(driver) else 1
    finally:
        try:
            driver.quit()
        except Exception:
            print("浏览器清理失败；不影响已确认的签到结果")


if __name__ == "__main__":
    sys.exit(main())
