# على Railway: استخدم worker (أو ابدأ مع ROZLF_ROLE=worker) لتفعيل Telegram polling
# web تعني "health فقط" بدون polling
worker: sh -c "python scripts/verify_build.py && exec python main.py"
web: sh -c "ROZLF_ROLE=web python scripts/verify_build.py && exec ROZLF_ROLE=web python main.py"
