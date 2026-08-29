#pragma once
#include "Domains/CotSDomainToolset.h"
class ICotSWorldDomain : public ICotSDomainToolset { public: virtual FString GetDomainName() const override { return TEXT("World"); } };
