import pytest

import biospecdb.util


@pytest.fixture
def spectral_data(tmp_path):
    return biospecdb.util.mock_single_spectral_data_file(path=tmp_path)
