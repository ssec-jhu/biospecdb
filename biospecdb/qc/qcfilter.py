from abc import ABC, abstractmethod


class QCValidationError(Exception):
    ...


class QcFilter(ABC):
    @abstractmethod
    def run(self, spectral_data):
        """
            param: spectral_data - uploader.models.SpectralData

            Raises QCValidationError.
        """
        ...


class QcSum(QcFilter):
    def run(self, spectral_data: "SpectralData"):  # noqa: F821
        df, _patient_id_from_file = spectral_data.get_spectral_df()
        res = df.sum(axis=0)["intensity"]
        return res


class QcTestDummyTrue(QcFilter):
    """ For testing purposes only. """
    def run(self, spectral_data):
        return True


class QcTestDummyFalse(QcFilter):
    """ For testing purposes only. """
    def run(self, spectral_data):
        return False
