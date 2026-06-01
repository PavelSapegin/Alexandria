from setuptools import setup

setup(
    name='tomd',
    version='0.1',
    py_modules=['tomd'],
    entry_points={
        'console_scripts': [
            'collect_code = tomd:main', # 'команда = имя_файла:функция_внутри'
        ],
    },
)
