from pathlib import Path
from threading import Event, Thread
from time import sleep

from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.service import Service
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from config import (
    AUTO_START_ENABLED,
    AUTO_START_POLL_INTERVAL_SECONDS,
    LIKES_URL,
    MAX_POSTS_PER_BATCH,
    MAX_SELECT_REFRESH_RETRIES,
    MAX_UNLIKE_REFRESH_RETRIES,
    POST_UNLIKE_DELAY_SECONDS,
    SELECT_BUTTON_TIMEOUT_SECONDS,
    START_READY_BUTTON_TEXT,
    WAIT_SECONDS,
)


CHECKBOX_XPATH = (
    "//div[@data-testid='bulk_action_checkbox']"
    "//div[@role='button' and @aria-label='Toggle checkbox']"
)
ACTION_UNLIKE_XPATH = (
    "(//div[@role='button' and @aria-label='Unlike' and not(ancestor::*[@role='dialog'])]"
    "|//button[@aria-label='Unlike' and not(ancestor::*[@role='dialog'])])[last()]"
)
CONFIRM_UNLIKE_XPATH = (
    "//button[.//div[normalize-space()='Unlike'] or .//span[normalize-space()='Unlike']]"
)


def wait_for_clickable_text(driver: webdriver.Edge, text: str) -> WebElement:
    xpath = f"//span[normalize-space()='{text}']|//div[normalize-space()='{text}']"
    return WebDriverWait(driver, WAIT_SECONDS).until(
        EC.element_to_be_clickable((By.XPATH, xpath))
    )


def try_wait_for_clickable_text(
    driver: webdriver.Edge, text: str, timeout: int = WAIT_SECONDS
) -> WebElement | None:
    xpath = f"//span[normalize-space()='{text}']|//div[normalize-space()='{text}']"
    try:
        return WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.XPATH, xpath))
        )
    except TimeoutException:
        return None


def js_click(driver: webdriver.Edge, element: WebElement) -> None:
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    driver.execute_script("arguments[0].click();", element)


def click_select_button(
    driver: webdriver.Edge, timeout: int = SELECT_BUTTON_TIMEOUT_SECONDS
) -> bool:
    driver.execute_script("window.scrollTo(0, 0);")
    sleep(0.5)

    for _ in range(3):
        select_button = try_wait_for_clickable_text(driver, "Select", timeout=timeout)
        if select_button is None:
            return False

        js_click(driver, select_button)
        sleep(0.75)

        if find_checkbox_buttons(driver):
            return True

        driver.execute_script("window.scrollTo(0, 0);")
        sleep(0.5)

    return False


def begin_batch_with_retries(driver: webdriver.Edge) -> bool:
    for attempt in range(1, MAX_SELECT_REFRESH_RETRIES + 1):
        if click_select_button(driver):
            if attempt > 1:
                print(
                    f"Select found after refresh retry {attempt}/{MAX_SELECT_REFRESH_RETRIES}."
                )
            return True

        print(
            f"Select not found within {SELECT_BUTTON_TIMEOUT_SECONDS} seconds. "
            f"Refreshing ({attempt}/{MAX_SELECT_REFRESH_RETRIES})..."
        )
        driver.refresh()
        WebDriverWait(driver, WAIT_SECONDS).until(EC.url_contains("/likes"))
        sleep(2)

    return False


def refresh_likes_page(driver: webdriver.Edge) -> None:
    driver.refresh()
    WebDriverWait(driver, WAIT_SECONDS).until(EC.url_contains("/likes"))
    sleep(2)


def find_checkbox_buttons(driver: webdriver.Edge) -> list[WebElement]:
    return driver.find_elements(By.XPATH, CHECKBOX_XPATH)


def click_checkbox_by_index(driver: webdriver.Edge, index: int) -> bool:
    for _ in range(4):
        checkboxes = find_checkbox_buttons(driver)
        if index >= len(checkboxes):
            return False

        try:
            js_click(driver, checkboxes[index])
            return True
        except (StaleElementReferenceException, ElementClickInterceptedException):
            sleep(0.25)

    return False


def select_posts(driver: webdriver.Edge, target_count: int) -> int:
    selected = 0
    previous_count = -1
    stagnant_scrolls = 0

    while selected < target_count:
        checkboxes = find_checkbox_buttons(driver)

        while selected < min(len(checkboxes), target_count):
            if not click_checkbox_by_index(driver, selected):
                break
            selected += 1
            sleep(0.15)

            if selected >= target_count:
                break

        if selected >= target_count:
            break

        current_count = len(checkboxes)
        if current_count == previous_count:
            stagnant_scrolls += 1
        else:
            stagnant_scrolls = 0

        if stagnant_scrolls >= 3:
            break

        previous_count = current_count
        driver.execute_script("window.scrollBy(0, Math.max(window.innerHeight, 900));")
        sleep(1)

    return selected


def click_unlike_flow(driver: webdriver.Edge) -> bool:
    for attempt in range(1, MAX_UNLIKE_REFRESH_RETRIES + 1):
        try:
            existing_confirm_buttons = len(
                driver.find_elements(By.XPATH, CONFIRM_UNLIKE_XPATH)
            )
            unlike_button = WebDriverWait(driver, WAIT_SECONDS).until(
                EC.element_to_be_clickable((By.XPATH, ACTION_UNLIKE_XPATH))
            )
            js_click(driver, unlike_button)

            confirm_button = WebDriverWait(driver, WAIT_SECONDS).until(
                lambda d: next(
                    (
                        button
                        for button in d.find_elements(By.XPATH, CONFIRM_UNLIKE_XPATH)
                        if button.is_displayed()
                    ),
                    None,
                )
            )
            js_click(driver, confirm_button)
            WebDriverWait(driver, WAIT_SECONDS).until(
                lambda d: len(d.find_elements(By.XPATH, CONFIRM_UNLIKE_XPATH))
                <= existing_confirm_buttons
            )
            return True
        except TimeoutException:
            print(
                f"Unlike flow did not appear in time. "
                f"Refreshing ({attempt}/{MAX_UNLIKE_REFRESH_RETRIES})..."
            )
            refresh_likes_page(driver)
            if not begin_batch_with_retries(driver):
                return False

            selected_count = select_posts(driver, MAX_POSTS_PER_BATCH)
            if selected_count == 0:
                print("After refresh, Select opened but no posts could be re-selected.")
                return False

    return False


def get_runtime_dir() -> Path:
    return Path(__file__).resolve().parent


def create_edge_driver() -> webdriver.Edge:
    runtime_dir = get_runtime_dir()
    driver_path = runtime_dir / "msedgedriver.exe"
    if not driver_path.exists():
        raise FileNotFoundError(
            f"Missing local Edge driver: {driver_path}. "
            "Run bootstrap.ps1 or place msedgedriver.exe in this folder."
        )

    service = Service(executable_path=str(driver_path))
    return webdriver.Edge(service=service)


def can_auto_start(driver: webdriver.Edge) -> bool:
    if "/your_activity/interactions/likes" not in driver.current_url:
        return False

    ready_button = try_wait_for_clickable_text(
        driver, START_READY_BUTTON_TEXT, timeout=1
    )
    return ready_button is not None


def wait_for_start_signal(driver: webdriver.Edge) -> None:
    if not AUTO_START_ENABLED:
        input(
            "Log in if needed, open the likes page, then press Enter to start..."
        )
        return

    manual_start_requested = Event()

    def wait_for_manual_start() -> None:
        try:
            input(
                "Waiting for Instagram likes page. Press Enter at any time to start manually...\n"
            )
            manual_start_requested.set()
        except EOFError:
            return

    Thread(target=wait_for_manual_start, daemon=True).start()
    print(
        "Waiting for the Instagram likes page. "
        "The script will start automatically when the Select button is available."
    )

    while True:
        if manual_start_requested.is_set():
            print("Manual start requested from console.")
            return

        if can_auto_start(driver):
            print("Likes page is ready. Starting automatically.")
            return

        sleep(AUTO_START_POLL_INTERVAL_SECONDS)


def main() -> None:
    driver = create_edge_driver()
    driver.maximize_window()

    try:
        driver.get(LIKES_URL)
        wait_for_start_signal(driver)

        total_processed = 0
        batch_number = 0

        while True:
            if not begin_batch_with_retries(driver):
                break

            selected_count = select_posts(driver, MAX_POSTS_PER_BATCH)
            if selected_count == 0:
                print("Select opened, but no selectable posts were found in this batch.")
                break

            if not click_unlike_flow(driver):
                print("Stopping because the unlike flow could not be recovered.")
                break

            sleep(POST_UNLIKE_DELAY_SECONDS)
            refresh_likes_page(driver)

            total_processed += selected_count
            batch_number += 1
            print(f"Completed batch {batch_number}: {selected_count} posts.")

        input(
            f"Finished after {batch_number} batches and {total_processed} posts. "
            "Press Enter to close the browser..."
        )
    except TimeoutException as exc:
        raise RuntimeError(
            "Instagram UI did not expose the expected button in time. "
            "The selectors likely need adjustment."
        ) from exc
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
