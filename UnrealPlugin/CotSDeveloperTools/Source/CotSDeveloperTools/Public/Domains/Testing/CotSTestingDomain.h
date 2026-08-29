#pragma once
#include "Domains/CotSDomainToolset.h"
class ICotSTestingDomain : public ICotSDomainToolset { public: virtual FString GetDomainName() const override { return TEXT("Testing"); } };
