# DSL: Сценарии и ресурсы в vikhry

## Virtual User (VU)

VU описывается как Python-класс с асинхронными шагами.

### Пример

```python
from vikhry import VU, resource, step


@resource(name="users")
async def create_user(id, ctx):
    return {"resource_id": "..."}


class MyVU(VU):
    async def on_start(self):
        self.user = await self.resources.acquire("users")

    @step(weight=3.0)
    async def get_catalog(self):
        await self.http.get("https://httpbin.org/get")

    @step(weight=1.0, requires=("is_authed",))
    async def create_order(self):
        await self.http.post("/order")
```

Декоратор, для указания шага:
```python
@step(
  name=None,
  weight=1.0,
  every_s=None,
  requires=(),
  timeout_s=None,
)
```

Описание:
- name - имя шага, по умолчанию — имя функции.
- weight — участвует в weighted random выборе.
- every_s — периодическое выполнение.
- requires — указания тех степов, которые должны быть выполнены до этого шага. Это может быть полезно для создания зависимостей между шагами, например, чтобы гарантировать, что пользователь аутентифицирован перед созданием заказа.
- timeout_s — максимальное время выполнения шага, после которого он будет считаться провалившимся.


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