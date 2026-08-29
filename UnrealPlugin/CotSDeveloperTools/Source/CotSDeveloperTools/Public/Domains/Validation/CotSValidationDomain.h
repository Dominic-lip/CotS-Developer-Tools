#pragma once
#include "Domains/CotSDomainToolset.h"
class ICotSValidationDomain : public ICotSDomainToolset { public: virtual FString GetDomainName() const override { return TEXT("Validation"); } };
