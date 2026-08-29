#pragma once
#include "Domains/CotSDomainToolset.h"
class ICotSDataDomain : public ICotSDomainToolset { public: virtual FString GetDomainName() const override { return TEXT("Data"); } };
