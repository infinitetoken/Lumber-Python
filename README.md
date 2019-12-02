# Lumber

Cloud logging for Python

- [Installation](#installation)
- [Usage](#usage)
- [App](#app)
- [License](#license)

## Installation

Use the package manager [pip3](https://pip.pypa.io/en/stable/) to install lumber-cloud.

```bash
pip install lumber-cloud
```

## Usage

Import the lumber_cloud module and initialize it with your app token.

```python
from lumber_cloud import Lumber

lumber = Lumber('your_app_token')
```

Create some logs with one of six levels.

```python
lumber.info('info')
lumber.debug('debug')
lumber.verbose('verbose')
lumber.warning('warning')
lumber.error('error')
lumber.critical('critical')
```

Optionally send stringified 'code' to any of the lumber methods.

```python
lumber.info('info', json.dumps({ key: 'value' }, null, 2))
```

## App

Lumber has a companion app available for MacOS, Windows, and LInux for viewing messages and errors logged to the cloud by using an optional API key. 
An API key can be obtained by creating a new app instance in the Lumber app.

![Lumber Screenshot](https://github.com/infinitetoken/Lumber-Swift/blob/master/Lumber.png)

[Download the Lumber app](https://www.infinitetoken.com/apps/lumber)

## License

Lumber is released under the MIT license. [See LICENSE](https://github.com/acwright/Lumber-Swift/blob/master/LICENSE) for details.
