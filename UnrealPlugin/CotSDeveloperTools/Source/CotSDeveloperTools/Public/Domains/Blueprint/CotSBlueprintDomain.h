#pragma once
#include "Domains/CotSDomainToolset.h"
class ICotSBlueprintDomain : public ICotSDomainToolset { public: virtual FString GetDomainName() const override { return TEXT("Blueprint"); } };
