# DSL: Сценарии и ресурсы в vikhry

## Virtual User (VU)

VU описывается как Python-класс с асинхронными шагами.

### Пример

```python
from vikhry import VU, emit_metric, metric, resource, step


@resource(name="users")
async def create_user(id, ctx):
    return {"resource_id": "..."}


class MyVU(VU):
    async def on_init(self, tenant: str, warmup: int = 1):
        self.tenant = tenant
        self.warmup = warmup

    async def on_start(self):
        self.user = await self.resources.acquire("users")

    @step(weight=3.0)
    async def get_catalog(self):
        await self.http.get("https://httpbin.org/get")

    @step(weight=1.0, requires=("is_authed",))
    async def create_order(self):
        await emit_metric(name="order_validation", status=True, time=1.2, phase="before_request")
        await self.http.post("/order")

    @metric(name="helper_auth", component="auth")
    async def helper_auth(self):
        await self.http.post("/auth")
```

Для кастомизации HTTP-клиента через фабрику в `on_init`:

```python
from vikhry import ReqwestClient, VU

class MyVU(VU):
    http = ReqwestClient(timeout=5)

    async def on_init(self, base_url: str):
        self.http = self.http(base_url=base_url)
```

Параметры `on_init` orchestrator извлекает из scenario-файла и отдает через:
- `GET /scenario/on_init_params`

Затем эти параметры можно передать в:
- `POST /start_test` через поле `init_params`
- `vikhry test start --init-param key=value` или `--init-params-json '{...}'`

Сценарий запускается worker'ом через CLI:

```bash
vikhry worker start --scenario my_load.scenarios:MyVU --http-base-url https://api.example.com
```

Декоратор, для указания шага:
```python
@step(
  name=None,
  weight=1.0,
  every_s=None,
  requires=(),
  timeout=None,
  **strategy_kwargs,
)
```

Описание:
- name - имя шага, по умолчанию — имя функции.
- weight — участвует в weighted random выборе.
- every_s — периодическое выполнение.
- requires — указания тех степов, которые должны быть выполнены до этого шага. Это может быть полезно для создания зависимостей между шагами, например, чтобы гарантировать, что пользователь аутентифицирован перед созданием заказа.
- timeout — максимальное время выполнения шага, после которого он будет считаться провалившимся.
- `**strategy_kwargs` — произвольные параметры шага, доступные стратегиям через `bound_step.spec.strategy_kwargs`.

Runtime behavior:
- шаги выбираются по weighted random среди eligible step;
- `requires` проверяются по именам успешно выполненных step;
- `every_s` ограничивает частоту повторного запуска шага;
- по каждому запуску шага worker пишет событие метрики (`name`, `step`, `status`, `time`) в `metric:worker:{worker_id}`.
- HTTP-клиент автоматически отправляет метрики по каждому запросу, где `name` = path (например `/page1`).
- для ручной метрики используйте `await emit_metric(...)`, для метрики вокруг функции — `@metric(...)`.


## Глобальные ресурсы

Ресурсы описываются отдельными функциями с декоратором.

Пример:

```python
@resource(
  name="users"
)
async def make_user(id, ctx):
    resp = await ctx.http.post("/register")
    return resp.json()
```

Каждая функция создающая ресурсы принимает несколько параметров:
1. id - уникальный идентификатор ресурса, который будет использоваться для его получения и удаления.
2. ctx - контекст, который содержит полезные об окружении (данные о воркере, http клиент и т.д.)

В worker runtime `self.resources.acquire(name)` получает ресурс из глобального Redis-пула, а
`self.resources.release(name, resource_id)` возвращает его обратно.
