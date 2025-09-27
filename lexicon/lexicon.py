# epicservice/lexicon/lexicon.py

class Lexicon:
    """
    Клас, що містить усі текстові константи (лексикон) для бота.
    """
    # --- Загальні команди та привітання ---
    CMD_START_USER = "👋 Вітаю! Я допоможу вам знайти товари та створити списки. Оберіть дію:"
    CMD_START_ADMIN = "👑 Вітаю, Адміністраторе! Вам доступний розширений функціонал. Оберіть дію:"

    # --- Тексти для Reply-клавіатур (головне меню) ---
    BUTTON_NEW_LIST = "Новий список"
    BUTTON_MY_LIST = "Мій список"
    BUTTON_ARCHIVE = "🗂️ Архів списків"
    BUTTON_ADMIN_PANEL = "👑 Адмін-панель"
    BUTTON_CANCEL = "❌ Скасувати"
    
    # --- Тексти-підказки в полі вводу ---
    PLACEHOLDER_USER = "Введіть артикул або назву товару..."
    PLACEHOLDER_ADMIN = "Введіть запит або оберіть команду..."

    # --- Тексти для Inline-клавіатур (кнопки в повідомленнях) ---
    INLINE_BUTTON_NEW_LIST = "🆕 Створити новий список"
    INLINE_BUTTON_MY_LIST = "📋 Мій поточний список"
    INLINE_BUTTON_ARCHIVE = "🗂️ Архів збережених списків"
    INLINE_BUTTON_ADMIN_PANEL = "⚙️ Панель Адміністратора"
    BUTTON_BACK_TO_MAIN_MENU = "↩️ На головну"
    
    BUTTON_CANCEL_INPUT = "❌ Скасувати введення"
    BUTTON_BACK_TO_SEARCH = "⬅️ Назад до результатів"

    BUTTON_IMPORT_PRODUCTS = "📥 Імпорт товарів з Excel"
    BUTTON_EXPORT_STOCK = "📊 Вивантажити залишки"
    EXPORT_COLLECTED_BUTTON = "📦 Вивантажити зведення по зібраному"
    BUTTON_SUBTRACT_COLLECTED = "📉 Відняти зібране зі складу"
    BUTTON_USER_ARCHIVES = "👥 Архіви користувачів"
    BUTTON_DELETE_ALL_LISTS = "🗑️ Видалити всі списки"
    BUTTON_STOCK_STATUS = "📈 Стан складу"
    BUTTON_COLLECTION_STATUS = "📋 Стан збору"
    
    BUTTON_USER_LIST_ITEM = "Користувач {user_id} (списκів: {lists_count})"
    BUTTON_BACK_TO_ADMIN_PANEL = "⬅️ Назад до адмін-панелі"
    BUTTON_PACK_IN_ZIP = "📦 Запакувати все в ZIP-архів"
    BUTTON_BACK_TO_USER_LIST = "⬅️ Назад до списку користувачів"
    BUTTON_ADD_ALL = "✅ Додати все ({quantity} шт.)"
    BUTTON_ADD_CUSTOM = "📝 Ввести іншу кількість"
    BUTTON_CONFIRM_YES = "✅ Так"
    BUTTON_CONFIRM_NO = "❌ Ні"
    BUTTON_NOTIFY_USERS = "🗣️ Надіслати сповіщення"
    BUTTON_FORCE_SAVE = "💾 Примусово зберегти"
    BUTTON_YES_NOTIFY = "✅ Так, сповістити"
    BUTTON_NO_NOTIFY = "❌ Ні, тихий режим"
    SAVE_LIST_BUTTON = "💾 Зберегти та відкласти"
    CANCEL_LIST_BUTTON = "❌ Скасувати список"
    EDIT_LIST_BUTTON = "✏️ Редагувати"

    SEARCH_TOO_SHORT = "⚠️ Будь ласка, введіть для пошуку не менше 3 символів."
    SEARCH_NO_RESULTS = "На жаль, за вашим запитом нічого не знайдено."
    SEARCH_MANY_RESULTS = "Знайдено декілька варіантів. Будь ласка, оберіть потрібний:"
    PRODUCT_CARD_TITLE = "✅ *Знайдено товар*"
    
    PRODUCT_CARD_TEMPLATE = (
        f"{PRODUCT_CARD_TITLE}\n\n"
        "📝 *Назва:* {name}\n"
        "🏢 *Відділ:* {department}\n"
        "📂 *Група:* {group}\n"
        "⏳ *Без руху (міс):* {months_no_movement}\n"
        "💰 *Сума залишку:* {stock_sum} грн\n"
        "📦 *Доступно для збирання:* {available_qty}\n"
        "🛒 *В резерві (з вашим списком):* {reserved_qty} ({reserved_sum} грн)"
    )

    NEW_LIST_CONFIRM = (
        "⚠️ Ви впевнені, що хочете створити новий список?\n"
        "**Весь поточний незбережений список буде видалено!**"
    )
    NEW_LIST_CONFIRMED = "✅ Створено новий порожній список. Тепер шукайте товари та додавайте їх."
    ACTION_CANCELED = "Дію скасовано."
    CANCEL_LIST_CONFIRM = "Ви впевнені, що хочете видалити поточний список? Всі незбережені товари будуть видалені."
    LIST_CANCELED = "✅ Ваш поточний список було успішно видалено."

    LIST_EDIT_MODE_TITLE = "✍️ *Режим редагування:*"
    LIST_EDIT_PROMPT = "Натисніть на товар, кількість якого хочете змінити."
    EDIT_ITEM_QUANTITY_PROMPT = "Введіть нову кількість для товару:\n{product_name}"
    ITEM_QUANTITY_UPDATED = "✅ Кількість для товару `{article}` оновлено на *{quantity}* шт."
    ITEM_REMOVED_FROM_LIST = "🗑️ Товар `{article}` видалено зі списку."

    EMPTY_LIST = "Ваш список порожній. Знайдіть товар, щоб додати його."
    MY_LIST_TITLE = "*Ваш поточний список (Відділ: {department}):*\n"
    MY_LIST_ITEM = "{i}. `{article}` ({name})\n   Кількість: *{quantity}*"
    
    PRODUCT_NOT_FOUND = "Помилка: товар не знайдено в базі даних."
    DEPARTMENT_MISMATCH = "❌ **Помилка!** Усі товари в одному списку повинні бути з одного відділу (`{department}`).\n\nСтворіть новий список для товарів з іншого відділу."
    ITEM_ADDED_TO_LIST = "Товар `{article}` у кількості *{quantity}* шт. додано до списку."
    ENTER_QUANTITY = "Введіть кількість для товару:\n{product_name}"
    SAVING_LIST_PROCESS = "Перевіряю залишки та формую списки... Це може зайняти декілька секунд."
    TRANSACTION_ERROR = "Сталася критична помилка під час збереження. Зміни було скасовано. Спробуйте зберегти список знову."
    MAIN_LIST_SAVED = "✅ **Основний список** збережено та зарезервовано."
    SURPLUS_LIST_CAPTION = "⚠️ **УВАГА!**\nЦе список товарів, яких **не вистачило на складі** (лишки)."
    PROCESSING_COMPLETE = "Обробку завершено!"

    NO_ARCHIVED_LISTS = "У вас ще немає збережених списків."
    ARCHIVE_TITLE = "🗂️ *Ваш архів списків:*\n"
    ARCHIVE_ITEM = "{i}. `{file_name}` (від {created_date})"

    ADMIN_PANEL_GREETING = "Ви в панелі адміністратора. Оберіть дію:"
    
    STOCK_STATUS_REPORT_TITLE = "📈 *Стан складу за відділами (товари в наявності):*"
    COLLECTION_STATUS_REPORT_TITLE = "📋 *Стан збору за відділами (всі резерви):*"
    REPORT_DEPARTMENT_ITEM = "- Відділ `{dep_id}`: **{count}** арт."
    REPORT_EMPTY_DATA = "Немає даних для формування звіту."

    IMPORT_PROMPT = "Будь ласка, надішліть мені файл Excel (`.xlsx`) з оновленими залишками.\n\nДля скасування натисніть кнопку нижче."
    IMPORT_WRONG_FORMAT = "❌ Помилка. Будь ласка, надішліть файл у форматі `.xlsx`."
    IMPORT_PROCESSING = "Завантажую та перевіряю файл..."
    IMPORT_INVALID_COLUMNS = "❌ **Помилка валідації!**\nНазви колонок у файлі неправильні.\nОчікується: `в, г, н, к`.\nУ вашому файлі відсутні: `{columns}`."
    IMPORT_VALIDATION_ERRORS_TITLE = "❌ **У файлі знайдені помилки валідації:**\n\n"
    IMPORT_CRITICAL_READ_ERROR = "❌ Критична помилка при читанні файлу: {error}"
    IMPORT_STARTING = "Файл виглядає добре. Починаю імпорт та обнулення старих резервів..."
    IMPORT_CANCELLED = "Імпорт скасовано."
    IMPORT_INCORRECT_FILE = "Будь ласка, надішліть документ (файл Excel) або натисніть 'Скасувати'."
    IMPORT_SYNC_ERROR = "❌ Сталася критична помилка під час синхронізації з базою даних: {error}"
    
    IMPORT_REPORT_TITLE = "✅ *Синхронізацію завершено!*\n"
    IMPORT_REPORT_ADDED = "➕ *Додано нових:* {added}"
    IMPORT_REPORT_UPDATED = "🔄 *Оновлено існуючих:* {updated}"
    IMPORT_REPORT_DEACTIVATED = "➖ *Деактивовано (зникли з файлу):* {deactivated}"
    IMPORT_REPORT_REACTIVATED = "♻️ *Повторно активовано:* {reactivated}\n"
    IMPORT_REPORT_TOTAL = "🗃️ *Всього активних артикулів у базі:* {total}"
    IMPORT_REPORT_SUCCESS_CHECK = "✅ *Перевірка пройшла успішно:* кількість у базі співпадає з файлом ({count})."
    IMPORT_REPORT_FAIL_CHECK = "⚠️ *Увага, розбіжність:* у базі {db_count}, а у файлі {file_count} унікальних артикулів."

    DELETE_ALL_LISTS_CONFIRM = "🔴 **УВАГА!**\n\nВи збираєтесь видалити **ВСІ** збережені списки **ВСІХ** користувачів та їхні файли. Ця дія **НЕЗВОРОТНЯ**.\n\nВи впевнені?"
    DELETE_ALL_LISTS_SUCCESS = "✅ Всі збережені списки ({count} шт.) та їхні файли було успішно видалено."
    DELETE_ALL_LISTS_CANCELLED = "Дію скасовано. Всі списки на місці."
    NO_LISTS_TO_DELETE = "Немає збережених списків для видалення."
    NO_USERS_WITH_ARCHIVES = "Жоден користувач ще не зберіг жодного списку."
    CHOOSE_USER_TO_VIEW_ARCHIVE = "Оберіть користувача для перегляду його архіву:"
    USER_HAS_NO_ARCHIVES = "У цього користувача немає збережених списків."
    USER_ARCHIVE_TITLE = "🗂️ *Архів користувача `{user_id}`:*\n"
    NO_FILES_TO_ARCHIVE = "Немає файлів для додавання до архіву."
    PACKING_ARCHIVE = "Почав пакування архівів для користувача `{user_id}`..."
    ZIP_ARCHIVE_CAPTION = "ZIP-архів зі списками для користувача `{user_id}`."
    ZIP_ERROR = "Сталася помилка під час створення ZIP-архіву: {error}"
    EXPORTING_STOCK = "Починаю формування звіту по залишкам..."
    STOCK_REPORT_CAPTION = "✅ Ось ваш звіт по актуальним залишкам."
    COLLECTED_REPORT_CAPTION = "✅ Ось зведений звіт по всім зібраним товарам."
    COLLECTED_REPORT_EMPTY = "Наразі немає жодного зібраного товару у збережених списках."
    COLLECTED_REPORT_PROCESSING = "Починаю формування зведеного звіту..."
    STOCK_REPORT_ERROR = "❌ Не вдалося створити звіт про залишки."
    SUBTRACT_PROMPT = "Будь ласка, надішліть мені звіт по зібраному (`.xlsx`), щоб відняти ці позиції від залишків на складі."
    SUBTRACT_PROCESSING = "Обробляю звіт по зібраному..."
    SUBTRACT_INVALID_COLUMNS = "❌ **Помилка!** Назви колонок у файлі для віднімання неправильні.\nОчікується: `Відділ, Група, Назва, Кількість`.\nУ вашому файлі: `{columns}`."
    SUBTRACT_REPORT_TITLE = "✅ *Віднімання зібраного завершено!*\n"
    SUBTRACT_REPORT_PROCESSED = "🔄 *Опрацьовано рядків:* {processed}"
    SUBTRACT_REPORT_NOT_FOUND = "⚠️ *Не знайдено в базі:* {not_found}"
    SUBTRACT_REPORT_ERROR = "❌ *Помилки (нечислові залишки):* {errors}"
    
    ACTIVE_LISTS_BLOCK = (
        "🔴 **Дію заблоковано!**\n\n"
        "Неможливо виконати операцію, оскільки наступні користувачі мають незавершені списки:\n"
        "{users_info}\n\n"
        "Оберіть дію:"
    )
    NOTIFICATIONS_SENT = "✅ Сповіщення успішно надіслано вказаним користувачам."
    USER_SAVE_LIST_NOTIFICATION = "❗️ **Будь ласка, збережіть ваш поточний список!**\nАдміністратор планує оновити базу даних. Незавершені списки можуть бути втрачені або збережені примусово."
    
    IMPORT_ASK_FOR_NOTIFICATION = "Сповістити всіх користувачів про це оновлення?"
    BROADCAST_STARTING = "✅ Імпорт завершено. Починаю розсилку сповіщень користувачам..."
    BROADCAST_SKIPPED = "✅ Імпорт завершено. Сповіщення користувачам не надсилались ('тихий режим')."
    
    # --- ОНОВЛЕНИЙ ШАБЛОН СПОВІЩЕННЯ (З ЖИРНИМ ШРИФТОМ) ---
    USER_IMPORT_NOTIFICATION_TITLE = "✅ **Базу товарів оновлено!**\n"
    USER_IMPORT_NOTIFICATION_SUMMARY = (
        "**Кількість артикулів:** *{total_in_db} шт.*\n"
        "**Загальна сума збору:** *{total_sum} грн*\n"
    )
    USER_IMPORT_NOTIFICATION_DETAILS = (
        "➕ *Додано нових:* {added}\n"
        "🔄 *Оновлено існуючих:* {updated}\n"
        "➖ *Деактивовано:* {deactivated}\n"
    )
    USER_IMPORT_NOTIFICATION_DEPARTMENTS_TITLE = "📦 *Актуальна кількість артикулів по відділах:*\n"
    USER_IMPORT_NOTIFICATION_DEPARTMENT_ITEM = "- Відділ `{dep_id}`: **{count}** арт."

    DELETE_WARNING_MESSAGE = "❗️ **Увага!**\n\nВаші збережені списки, старші за 36 годин, будуть видалені через 12 годин. Якщо ви хочете зберегти їх, будь ласка, завантажте ZIP-архів зі свого архіву."
    
    UNEXPECTED_ERROR = (
        "😔 **Ой, щось пішло не так...**\n"
        "Виникла непередбачена помилка. Ми вже отримали сповіщення і працюємо над її вирішенням. Спробуйте повторити дію пізніше."
    )

LEXICON = Lexicon()