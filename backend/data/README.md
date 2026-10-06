# Data

`raw/` is git-ignored: datasets are never committed.

Put the 9 CSVs of the [Olist Brazilian E-Commerce dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)
in `raw/` (unzipped), then from `backend/`:

```sh
make up          # postgres + redis
make load-data   # applies migrations, then truncates and reloads the shop schema
```
