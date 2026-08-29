#pragma once
#include "Domains/CotSDomainToolset.h"
class ICotSAnimationDomain : public ICotSDomainToolset { public: virtual FString GetDomainName() const override { return TEXT("Animation"); } };
