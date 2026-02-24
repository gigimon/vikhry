# DSL: Сценарии и ресурсы в vikhry

## Virtual User (VU)

VU описывается как Python-класс с асинхронными шагами.

### Пример

```python
from vikhry import BaseVU, resource, step


@resource(kind="users", concurrency=20, batch_size=100)
async def create_user(ctx):
    return {"resource_id": "..."}


class MyVU(BaseVU):
    async def on_start(self):
        self.user = await self.resources.acquire("users")

    @step(weight=3.0)
    async def get_catalog(self):
        await self.http.get("https://httpbin.org/get")

    @step(weight=1.0, requires=("is_authed",))
    async def create_order(self):
        await self.http.post("/order")
```

```python
@step(
  name=None,
  weight=1.0,
  every_s=None,
  requires=(),
  timeout_s=None,
  retry=0,
)
```

Описание:
- weight — участвует в weighted random выборе.
- every_s — периодическое выполнение.
- requires — указания тех степов, которые должны быть выполнены до этого шага. Это может быть полезно для создания зависимостей между шагами, например, чтобы гарантировать, что пользователь аутентифицирован перед созданием заказа.


## Глобальные ресурсы

Ресурсы описываются отдельными функциями с декоратором.

Пример:

```python
@resource(
  kind="user",
  concurrency=5,
)
async def make_user(ctx):
    resp = await ctx.http.post("/register")
    return resp.json()
```
